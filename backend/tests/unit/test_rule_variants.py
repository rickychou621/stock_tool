from datetime import date, timedelta
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.backtest.models import BacktestCalendarMonth, BacktestCoverage
from app.backtest.simulation import adjusted_bars, simulate, usable
from app.market_data.models import Stock, StockDividendEvent, StockPriceDaily, StockPriceEvent
from app.research.rule_variants import (
    VARIANTS,
    DataUnavailable,
    Variant,
    liquidity_group,
    load_benchmark,
    load_calendar,
    load_data,
    markdown,
    process_stock,
    statistics,
    summarize,
    trades_for,
)
from app.trading_costs import TradingCosts


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("研究工具不得連外")

    monkeypatch.setattr(httpx.Client, "__init__", forbidden)
    monkeypatch.setattr(httpx.AsyncClient, "__init__", forbidden)
    monkeypatch.setattr("app.market_data.service.FinMindClient", forbidden)
    monkeypatch.setattr("app.market_data.service.MarketDataService.sync_daily_prices", forbidden)


def synthetic(met, slope=1, turnover=1e8):
    dates = [date(2026, 1, 1) + timedelta(days=i) for i in range(len(met))]
    signals = [
        dict(
            date=d.isoformat(), isMet=m, conditions=[dict(indicators={"mid": 100, "slope": slope})]
        )
        for d, m in zip(dates, met, strict=True)
    ]
    prices = {d.isoformat(): SimpleNamespace(open=100 + i) for i, d in enumerate(dates)}
    turns = {d.isoformat(): turnover for d in dates}
    return dates, signals, prices, turns


def replay(met, variant, slope=1, turnover=1e8):
    dates, signals, prices, turns = synthetic(met, slope, turnover)
    return trades_for("TEST", signals, prices, turns, "stock", variant, TradingCosts(), {}, dates)


@pytest.mark.parametrize("variant", VARIANTS, ids=lambda v: v.name)
def test_all_seven_variants_execute_next_open(variant):
    trades = replay([False, True, True, False, False, False, False], variant)
    assert len(trades) == 1
    trade = trades[0]
    assert trade["signal_date"] == "2026-01-02"
    assert trade["entry"] == "2026-01-03"
    assert trade["exit"] == f"2026-01-0{4 + variant.exit_days}"
    assert trade["holding_days"] == 1 + variant.exit_days
    assert trade["signal_turnover"] == 1e8
    assert trade["gross"] == pytest.approx((103 + variant.exit_days) / 102 - 1)
    assert trade["net"] == TradingCosts().net_return(102, 103 + variant.exit_days)
    assert trade["excess"] is None


@pytest.mark.parametrize("threshold", [0.005, 0.01])
@pytest.mark.parametrize("delta,accepted", [(-1e-8, False), (0, True), (1e-8, True)])
def test_slope_boundary(threshold, delta, accepted):
    trades = replay(
        [True, False, False], Variant("slope", min_slope=threshold), slope=100 * (threshold + delta)
    )
    assert bool(trades) == accepted


@pytest.mark.parametrize(
    "turnover,accepted", [(None, False), (99999999, False), (100000000, True), (100000001, True)]
)
def test_turnover_boundary_and_signal_day(turnover, accepted):
    dates, signals, prices, turns = synthetic([True, False, False], turnover=turnover)
    turns[dates[1].isoformat()] = 0  # Fill-day turnover must not filter the entry.
    trades = trades_for(
        "T", signals, prices, turns, "stock", VARIANTS[3], TradingCosts(), {}, dates
    )
    assert bool(trades) == accepted


def test_buffer_resets_on_recovery_and_requires_consecutive_failures():
    trades = replay([True, False, True, False, False, False], VARIANTS[1])
    assert len(trades) == 1
    assert trades[0]["exit"] == "2026-01-06"


def test_rejected_entry_cannot_enter_on_continued_signal():
    dates, signals, prices, turns = synthetic([True, True, False, False])
    turns[dates[0].isoformat()] = 0
    assert not trades_for(
        "T", signals, prices, turns, "stock", VARIANTS[3], TradingCosts(), {}, dates
    )


@pytest.mark.parametrize("met", [[True], [True, True], [True, False]])
@pytest.mark.parametrize("variant", VARIANTS, ids=lambda v: v.name)
def test_unfilled_open_and_pending_sell_excluded(met, variant):
    assert replay(met, variant) == []


def test_combined_requires_both_filters_and_missing_indicators_fail():
    assert not replay([True, False, False, False], VARIANTS[4], slope=0.5)
    assert not replay([True, False, False, False], VARIANTS[4], turnover=1e7)
    assert not replay([True, False, False], VARIANTS[2], slope=None)


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    for model in (
        Stock,
        StockPriceDaily,
        StockDividendEvent,
        StockPriceEvent,
        BacktestCoverage,
        BacktestCalendarMonth,
    ):
        model.__table__.create(engine)
    with Session(engine) as session:
        session.add(Stock(ticker="TEST", name="test", market="上市"))
        for i, value in enumerate([10, 10, 12, 14, 16, 8, 6, 10, 12]):
            session.add(
                StockPriceDaily(
                    id=i + 1,
                    ticker="TEST",
                    trade_date=date(2026, 1, 5) + timedelta(days=i),
                    open=value,
                    high=value + 1,
                    low=value - 1,
                    close=value,
                    volume=100,
                    adj_open=value,
                    adj_high=value + 1,
                    adj_low=value - 1,
                    adj_close=value,
                    turnover=1e8,
                )
            )
        session.add(
            StockDividendEvent(ticker="TEST", ex_dividend_date=date(2026, 1, 10), cash_dividend=0.1)
        )
        session.add(
            StockPriceEvent(
                ticker="TEST",
                event_date=date(2026, 1, 9),
                event_type="split",
                before_close=14,
                reference_price=7,
                source="test",
            )
        )
        session.commit()
        yield session
    engine.dispose()


def rule():
    return SimpleNamespace(
        id=1,
        name="test",
        logic_operator="AND",
        conditions=[
            SimpleNamespace(
                condition_id="bollinger_mid_up",
                params={"period": 2, "slope_lookback": 1},
                sort_order=0,
            )
        ],
    )


def test_sqlite_baseline_matches_production_and_loader_is_read_only(db):
    dates = [date(2026, 1, 5) + timedelta(days=i) for i in range(9)]
    statements = []
    event.listen(
        db.bind,
        "before_cursor_execute",
        lambda conn, cursor, statement, *args: statements.append(statement),
    )
    raw, events, turnover = load_data(db, "TEST", dates[0], dates[-1], dates)
    assert len(events) == 2
    payload = simulate(rule(), "TEST", raw, events, dates[0], dates[-1], dates)
    prices = {
        b.trade_date.isoformat(): b for b in adjusted_bars([b for b in raw if usable(b)], events)
    }
    benchmark = {d.isoformat(): {"open": 100 + i} for i, d in enumerate(dates)}
    trades = trades_for(
        "TEST",
        payload["signals"],
        prices,
        turnover,
        "etf",
        VARIANTS[0],
        TradingCosts(),
        benchmark,
        dates,
    )
    closed = [t for t in payload["trades"] if t["status"] == "closed"]
    assert len(closed) == len(trades) > 0
    for a, b in zip(closed, trades, strict=True):
        assert (a["entryDate"], a["exitDate"], a["holdingDays"]) == (
            b["entry"],
            b["exit"],
            b["holding_days"],
        )
        assert abs(a["returnRate"] - b["gross"]) < 1e-9
        assert b["net"] == TradingCosts().net_return(a["entryPrice"], a["exitPrice"], "etf")
        assert b["excess"] == pytest.approx(
            b["net"] - (benchmark[b["exit"]]["open"] / benchmark[b["entry"]]["open"] - 1)
        )
    assert all(s.lstrip().upper().startswith("SELECT") for s in statements)


def test_gap_is_skipped_and_reason_recorded_without_fetch(db):
    dates = [date(2026, 1, 5) + timedelta(days=i) for i in range(10)]
    with pytest.raises(DataUnavailable, match="缺 1 個交易日"):
        load_data(db, "TEST", dates[0], dates[-1], dates)
    result = process_stock(
        lambda: Session(db.bind),
        "TEST",
        rule(),
        dates[0],
        dates[-1],
        dates[0],
        dates,
        "stock",
        TradingCosts(),
        {},
    )
    assert result["trades"] == []
    assert "行情缺口" in result["reason"]
    with pytest.raises(DataUnavailable):
        load_benchmark(db, dates[0], dates[-1], dates)


def test_verified_suspension_gap_allowed_but_missing_record_rejected(db):
    dates = [date(2026, 1, 5) + timedelta(days=i) for i in range(10)]
    coverage = BacktestCoverage(
        ticker="TEST",
        start_date=dates[0],
        end_date=dates[-1],
        dates=[d.isoformat() for d in dates[:-1]],
    )
    db.add(coverage)
    db.commit()
    assert len(load_data(db, "TEST", dates[0], dates[-1], dates)[0]) == 9
    coverage.dates = [d.isoformat() for d in dates]
    db.commit()
    with pytest.raises(DataUnavailable):
        load_data(db, "TEST", dates[0], dates[-1], dates)


def test_calendar_missing_stale_and_cached_no_network(db):
    with pytest.raises(DataUnavailable, match="交易日曆"):
        load_calendar(db, date(2026, 1, 1), date(2026, 1, 10))
    cached = BacktestCalendarMonth(
        month="2026-01", checked_on=date(2026, 1, 9), dates=["2026-01-05", "2026-01-09"]
    )
    db.add(cached)
    db.commit()
    with pytest.raises(DataUnavailable):
        load_calendar(db, date(2026, 1, 1), date(2026, 1, 10))
    cached.checked_on = date(2026, 1, 10)
    db.commit()
    assert load_calendar(db, date(2026, 1, 1), date(2026, 1, 10)) == [
        date(2026, 1, 5),
        date(2026, 1, 9),
    ]


@pytest.mark.parametrize(
    "turn,label",
    [
        (None, "無資料"),
        (9999999, "< 1,000 萬"),
        (10000000, "1,000 萬～1 億"),
        (99999999, "1,000 萬～1 億"),
        (100000000, "≥ 1 億"),
    ],
)
def test_liquidity_boundaries(turn, label):
    assert liquidity_group(turn) == label


def test_statistics_trim_missing_benchmark_and_empty_groups():
    trades = [
        dict(net=n, excess=e, ticker=t, holding_days=h)
        for n, e, t, h in [(-0.1, None, "A", 2), (0.2, 0.1, "B", 4), (10, -0.1, "B", 6)]
    ]
    s = statistics(trades)
    assert s["count"] == 3 and s["stock_count"] == 2
    assert s["win_rate"] == pytest.approx(2 / 3)
    assert s["median_net"] == 0.2 and s["median_holding_days"] == 4
    assert s["profit_factor"] == pytest.approx(102)
    assert s["trimmed_average_net"] == pytest.approx(0.05)
    assert s["positive_excess_rate"] == 0.5 and s["excess_count"] == 2
    assert statistics([])["average_net"] is None
    assert statistics(trades[:1])["trimmed_average_net"] is None
    assert statistics(trades * 34)["trimmed_count"] == 2


def test_report_groups_and_three_placeholders():
    trades = replay([True, False, False], VARIANTS[0])
    groups = summarize(trades, date(2023, 10, 19), date(2026, 10, 19))
    assert groups["進場年份：2026"]["原規則"]["count"] == 1
    assert groups["進場期間：2023-10～2024-12"]["原規則"]["count"] == 0
    report = markdown(
        dict(
            parameters=dict(universe="market", start="2023-10-19", end="2026-10-19", rule_id=1),
            universe_size=1,
            succeeded=1,
            skipped=[],
            benchmark_reason=None,
            statistics=groups,
        )
    )
    assert report.splitlines()[:3] == ["<!-- 結論待填 -->"] * 3
    assert report.count("| 變體 |") == 8


def test_corrupt_price_and_missing_adjustment_are_rejected(db):
    dates = [date(2026, 1, 5) + timedelta(days=i) for i in range(9)]
    bar = db.get(StockPriceDaily, 1)
    bar.adj_open = None
    db.commit()
    with pytest.raises(DataUnavailable, match="還原欄位"):
        load_data(db, "TEST", dates[0], dates[-1], dates)
    bar.adj_open, bar.open = 10, -1
    db.commit()
    with pytest.raises(DataUnavailable, match="負值"):
        load_data(db, "TEST", dates[0], dates[-1], dates)


def test_suspended_sessions_count_toward_holding_days():
    dates, signals, prices, turns = synthetic([True, True, False, False, False])
    # No signal/fill on Jan 3, but it remains an exchange session.
    signals.pop(2)
    trade = trades_for(
        "T", signals, prices, turns, "stock", VARIANTS[0], TradingCosts(), {}, dates
    )[0]
    assert trade["entry"] == "2026-01-02"
    assert trade["exit"] == "2026-01-05"
    assert trade["holding_days"] == 3


def test_cli_writes_strict_json_and_markdown_without_database(monkeypatch, tmp_path):
    import json

    from app.research import rule_variants as module

    result = dict(
        parameters=dict(universe="market", start="2023-10-19", end="2026-10-19", rule_id=1),
        universe_size=0,
        succeeded=0,
        skipped=[],
        trades=[],
        benchmark_reason="0050 無資料",
        statistics=summarize([], date(2023, 10, 19), date(2026, 10, 19)),
    )
    monkeypatch.setattr(module, "run_research", lambda args: result)
    json_path, md_path = tmp_path / "out.json", tmp_path / "out.md"
    module.main(["--universe", "market", "--out-json", str(json_path), "--out-md", str(md_path)])
    assert json.loads(json_path.read_text()) == result
    assert md_path.read_text().startswith("<!-- 結論待填 -->\n" * 3)
    assert "0050 無資料" in md_path.read_text()


def test_gaps_before_listing_or_confirmed_absent_are_not_gaps():
    from datetime import date

    from app.research.rule_variants import DataUnavailable, load_data

    class FakeScalars(list):
        pass

    class FakeDb:
        def scalars(self, _):
            return FakeScalars()

        def get(self, *_):
            return None

    days = [date(2026, 1, 5), date(2026, 1, 6)]
    # Listed after both days: nothing is expected yet, so no gap.
    raw, _, _ = load_data(FakeDb(), "9999", days[0], days[-1], days, listed_on=date(2026, 2, 1))
    assert raw == []
    # Confirmed absent on both days by market batch coverage: no gap.
    absent = {d: {"9999"} for d in days}
    raw, _, _ = load_data(FakeDb(), "9999", days[0], days[-1], days, absent=absent)
    assert raw == []
    # Unconfirmed missing days remain a gap.
    try:
        load_data(FakeDb(), "9999", days[0], days[-1], days)
    except DataUnavailable:
        pass
    else:
        raise AssertionError("unconfirmed gap must be skipped")
