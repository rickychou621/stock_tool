import random
from datetime import date, timedelta
from statistics import mean
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
    add_baselines,
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


@pytest.mark.parametrize("variant", VARIANTS[3:10], ids=lambda v: v.name)
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
        "T", signals, prices, turns, "stock", VARIANTS[6], TradingCosts(), {}, dates
    )
    assert bool(trades) == accepted


def test_buffer_resets_on_recovery_and_requires_consecutive_failures():
    trades = replay([True, False, True, False, False, False], VARIANTS[4])
    assert len(trades) == 1
    assert trades[0]["exit"] == "2026-01-06"


def test_rejected_entry_cannot_enter_on_continued_signal():
    dates, signals, prices, turns = synthetic([True, True, False, False])
    turns[dates[0].isoformat()] = 0
    assert not trades_for(
        "T", signals, prices, turns, "stock", VARIANTS[6], TradingCosts(), {}, dates
    )


@pytest.mark.parametrize("met", [[True], [True, True], [True, False]])
@pytest.mark.parametrize("variant", VARIANTS[3:10], ids=lambda v: v.name)
def test_unfilled_open_and_pending_sell_excluded(met, variant):
    assert replay(met, variant) == []


def test_combined_requires_both_filters_and_missing_indicators_fail():
    assert not replay([True, False, False, False], VARIANTS[7], slope=0.5)
    assert not replay([True, False, False, False], VARIANTS[7], turnover=1e7)
    assert not replay([True, False, False], VARIANTS[5], slope=None)


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
        VARIANTS[3],
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
    trades = replay([True, False, False], VARIANTS[3])
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
    for heading in (
        "平均超額（全市場）",
        "超額為正比例（全市場）",
        "平均超額（同股隨機）",
        "超額為正比例（同股隨機）",
    ):
        assert report.count(heading) == 8
    assert (
        "全市場＝同期間全部股票等權平均；同股隨機＝同一股票隨機進場、"
        "持有相同交易日數，各 20 次平均。皆已扣成本。"
    ) in report
    assert all(len(line.split("|")) == 20 for line in report.splitlines() if line.startswith("|"))


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
        "T", signals, prices, turns, "stock", VARIANTS[3], TradingCosts(), {}, dates
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


@pytest.mark.parametrize("missing_exit", [False, True])
def test_market_equal_weights_and_missing_endpoint(missing_exit):
    days = [date(2026, 1, 5), date(2026, 1, 6)]
    entry, exit = [d.isoformat() for d in days]
    opens = {
        "A": {entry: 10, exit: 12},
        "B": {entry: 1000, exit: 900},
        "C": {entry: 20, **({} if missing_exit else {exit: 30})},
    }
    trade = dict(ticker="A", variant="原規則", entry=entry, exit=exit, holding_days=1, net=0.2)
    costs = TradingCosts(fee_discount=0.6)
    add_baselines([trade], opens, days, days[0], costs, min_stocks=2)
    ratio = mean([1.2, 0.9] if missing_exit else [1.2, 0.9, 1.5])
    assert trade["excess_market"] == pytest.approx(0.2 - costs.net_return(1, ratio, "stock"))
    add_baselines([trade], opens, days, days[0], costs)
    assert trade["excess_market"] is None


@pytest.mark.parametrize("size", [35, 8, 2])
def test_random_reproducible_returns_short_pool_and_no_pool(size):
    days = [date(2026, 1, 1) + timedelta(days=i) for i in range(size)]
    start = days[1]
    # Different price levels and a missing session catch compressed-calendar sampling.
    opens = {
        d.isoformat(): 10 + i * i
        for i, d in enumerate(days)
        if i != 4
    }
    holding = 2
    trade = dict(
        ticker="A", variant="原規則", entry=days[1].isoformat(),
        exit=days[-1].isoformat(), holding_days=holding, net=0.1,
    )
    costs = TradingCosts()
    eligible = [
        i for i in range(1, size - holding)
        if days[i].isoformat() in opens and days[i + holding].isoformat() in opens
    ]
    rng = random.Random(f"A|原規則|{trade['entry']}")
    selected = rng.sample(eligible, 20) if len(eligible) >= 20 else eligible
    expected = (
        0.1 - mean(
            costs.net_return(opens[days[i].isoformat()], opens[days[i + holding].isoformat()])
            for i in selected
        )
        if selected else None
    )
    add_baselines([trade], {"A": opens}, days, start, costs)
    first = trade["excess_random"]
    random.seed(987)
    add_baselines([trade], {"A": dict(reversed(list(opens.items())))}, days, start, costs)
    assert trade["excess_random"] == first
    assert first == pytest.approx(expected) if expected is not None else first is None


def test_new_statistics_use_independent_nonmissing_denominators():
    trades = [
        dict(
            ticker="A", net=0.1, excess=None, holding_days=2,
            excess_market=market, excess_random=rand,
        )
        for market, rand in [(0.2, None), (-0.1, 0.3), (None, 0), (None, -0.6)]
    ]
    stats = statistics(trades)
    assert stats["average_excess_market"] == pytest.approx(0.05)
    assert stats["positive_excess_market_rate"] == 0.5
    assert stats["average_excess_random"] == pytest.approx(-0.1)
    assert stats["positive_excess_random_rate"] == pytest.approx(1 / 3)
    for key in (
        "average_excess_market", "positive_excess_market_rate",
        "average_excess_random", "positive_excess_random_rate",
    ):
        assert statistics([])[key] is None


def test_process_stock_returns_only_usable_adjusted_opens(monkeypatch):
    from contextlib import nullcontext

    from app.conditions.types import ConditionBar
    from app.market_data.price_adjustment import PriceEvent
    from app.research import rule_variants as module

    days = [date(2026, 1, 5) + timedelta(days=i) for i in range(4)]
    raw = [
        ConditionBar(days[0], 100, 101, 99, 100, volume=100),
        ConditionBar(days[1], 0, 0, 0, 0, volume=0),
        ConditionBar(days[2], 50, 51, 49, 50, volume=100),
        ConditionBar(days[3], 55, 56, 54, 55, volume=100),
    ]
    events = [PriceEvent(days[2], 100, 50)]
    monkeypatch.setattr(module, "load_data", lambda *args: (raw, events, {}))
    monkeypatch.setattr(
        module, "simulate",
        lambda *args: dict(
            trades=[], signals=[], actualStart=str(days[0]), actualEnd=str(days[-1]),
        ),
    )
    result = process_stock(
        nullcontext, "A", rule(), days[0], days[-1], days[0], days,
        "stock", TradingCosts(), {},
    )
    assert result["reason"] is None
    assert result["opens"] == {
        str(days[0]): 50, str(days[2]): 50, str(days[3]): 55,
    }


@pytest.mark.parametrize("entry", ["pullback", "breakout"])
@pytest.mark.parametrize("history", [0, 18, 19, 20])
def test_entry_warmup_and_next_open(entry, history):
    dates, signals, prices, turns = trigger_data(entry, history)
    trades = trigger_trades(entry, dates, signals, prices, turns)
    assert bool(trades) == (history >= (19 if entry == "pullback" else 20))
    if trades:
        assert trades[0]["signal_date"] == str(dates[history])
        assert trades[0]["entry"] == str(dates[history + 1])
        assert trades[0]["exit"] == str(dates[history + 2])
        assert trades[0]["signal_turnover"] == turns[str(dates[history])]


def trigger_data(entry, history=20):
    from app.conditions.types import ConditionBar

    dates, signals, _, turns = synthetic([True] * (history + 1) + [False, False])
    prices = {
        str(day): ConditionBar(day, 100, 100, 100, 100, volume=100)
        for day in dates
    }
    day = dates[history]
    if entry == "pullback":
        # Exact low == MA20 * 1.01, with a valid OHLC bar and MA20 == 100.
        prices[str(dates[0])] = ConditionBar(dates[0], 98, 98, 98, 98, volume=100)
        if history >= 19:
            old = dates[history - 19]
            prices[str(old)] = ConditionBar(old, 98, 98, 98, 98, volume=100)
        prices[str(day)] = ConditionBar(day, 102, 102, 101, 102, volume=100)
    else:
        prices[str(day)] = ConditionBar(day, 101, 101, 100, 101, volume=100)
        turns[str(day)] = 2e8
    # Warmup prices exist even when simulation signals start later.
    return dates, signals[history:], dict(reversed(list(prices.items()))), turns


def trigger_trades(entry, dates, signals, prices, turns, **kwargs):
    return trades_for(
        "T", signals, prices, turns, "stock", Variant("trigger", entry=entry, **kwargs),
        TradingCosts(), {}, dates,
    )


@pytest.mark.parametrize(
    "low,close,met,accepted",
    [(101, 102, True, True), (101.00001, 102, True, False),
     (98, 99, True, False), (101, 102, False, False)],
)
def test_pullback_boundaries(low, close, met, accepted):
    from app.conditions.types import ConditionBar

    dates, signals, prices, turns = trigger_data("pullback")
    day = dates[20]
    prices[str(day)] = ConditionBar(day, close, max(102, close), low, close, volume=100)
    signals[0]["isMet"] = met
    assert bool(trigger_trades("pullback", dates, signals, prices, turns)) == accepted


@pytest.mark.parametrize(
    "turn,close,missing,met,accepted",
    [(2e8 - 1, 101, None, True, False), (2e8, 101, None, True, True),
     (2e8 + 1, 101, None, True, True), (2e8, 100, None, True, False),
     (None, 101, None, True, False), (2e8, 101, 0, True, False),
     (2e8, 101, 19, True, False), (2e8, 101, None, False, False)],
)
def test_breakout_boundaries(turn, close, missing, met, accepted):
    from app.conditions.types import ConditionBar

    dates, signals, prices, turns = trigger_data("breakout")
    day = dates[20]
    prices[str(day)] = ConditionBar(day, close, 1000, 100, close, volume=100)
    turns[str(day)] = turn
    if missing is not None:
        turns[str(dates[missing])] = None
    signals[0]["isMet"] = met
    assert bool(trigger_trades("breakout", dates, signals, prices, turns)) == accepted


@pytest.mark.parametrize("entry", ["pullback", "breakout"])
@pytest.mark.parametrize("filters", [{"min_slope": 0.02}, {"min_turn": 3e8}])
def test_trigger_preserves_optional_filters(entry, filters):
    assert not trigger_trades(entry, *trigger_data(entry), **filters)


@pytest.mark.parametrize("entry", ["pullback", "breakout"])
def test_continued_trend_and_reentry_after_exit(entry):
    from app.conditions.types import ConditionBar

    dates, signals, _, turns = synthetic([True] * 22 + [False, True, True, False, False])
    prices = {
        str(day): ConditionBar(day, 100 + i, 100 + i, 100 + i, 100 + i, volume=100)
        for i, day in enumerate(dates)
    }
    if entry == "pullback":
        prices = {
            str(day): ConditionBar(day, 100, 100, 100, 100, volume=100) for day in dates
        }
    else:
        turns[str(dates[20])] = 2e8
        turns[str(dates[23])] = 3e8
    trades = trigger_trades(entry, dates, signals, prices, turns)
    assert len(trades) == 2
    assert trades[0]["signal_date"] == str(dates[19 if entry == "pullback" else 20])
    assert trades[0]["exit"] == str(dates[23])
    assert trades[1]["signal_date"] == str(dates[23])
    assert trades[1]["entry"] == str(dates[24])
    assert trades[1]["exit"] == str(dates[26])


@pytest.mark.parametrize("field", ["pullback_pct", "breakout_lookback", "breakout_turnover_mult"])
@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf")])
def test_invalid_trigger_parameters(field, value):
    with pytest.raises(ValueError, match=field):
        Variant("invalid", **{field: value})


def test_variant_order_and_entry_validation():
    with pytest.raises(ValueError, match="entry"):
        Variant("invalid", entry="unknown")
    with pytest.raises(ValueError, match="整數"):
        Variant("invalid", breakout_lookback=1.5)
    assert [(v.name, v.entry, v.exit_days) for v in VARIANTS[10:]] == [
        ("拉回進場", "pullback", 1), ("拉回進場＋出場緩衝 2 天", "pullback", 2),
        ("放量突破", "breakout", 1), ("放量突破＋出場緩衝 2 天", "breakout", 2),
    ]


def test_process_stock_shares_features_across_variants(monkeypatch):
    from contextlib import nullcontext
    from unittest.mock import Mock

    from app.research import rule_variants as module

    dates, signals, prices, turns = trigger_data("breakout")
    monkeypatch.setattr(module, "load_data", lambda *args: (list(prices.values()), [], turns))
    monkeypatch.setattr(module, "adjusted_bars", lambda bars, events: bars)
    monkeypatch.setattr(module, "simulate", lambda *args: dict(
        trades=[], signals=signals, actualStart=str(dates[0]), actualEnd=str(dates[-1]),
    ))
    spy = Mock(wraps=module.entry_features)
    monkeypatch.setattr(module, "entry_features", spy)
    result = process_stock(
        nullcontext, "T", rule(), dates[0], dates[-1], dates[0], dates,
        "stock", TradingCosts(), {},
    )
    assert result["reason"] is None
    assert spy.call_count == 1


@pytest.mark.parametrize("entry", ["pullback", "breakout"])
def test_trigger_exit_buffer_and_no_future_leakage(entry):
    from app.conditions.types import ConditionBar

    dates, signals, prices, turns = trigger_data(entry)
    extra = dates[-1] + timedelta(days=1)
    dates.append(extra)
    signals.append(dict(date=str(extra), isMet=False, conditions=[]))
    prices[str(extra)] = ConditionBar(extra, 110, 1e9, 1, 1e8, volume=100)
    turns[str(extra)] = 1e15
    trades = trigger_trades(entry, dates, signals, prices, turns, exit_days=2)
    assert len(trades) == 1
    assert trades[0]["signal_date"] == signals[0]["date"]
    assert trades[0]["exit"] == str(extra)


def test_configurable_breakout_window_and_threshold():
    dates, signals, prices, turns = trigger_data("breakout", history=5)
    turns[signals[0]["date"]] = 1.5e8
    assert len(trigger_trades(
        "breakout", dates, signals, prices, turns,
        breakout_lookback=5, breakout_turnover_mult=1.5,
    )) == 1
    assert not trigger_trades("breakout", dates, signals, prices, turns)


def test_breakout_counts_usable_bars_not_calendar_days():
    dates, signals, prices, turns = trigger_data("breakout", history=21)
    del prices[str(dates[10])]
    turns[str(dates[10])] = None
    assert len(trigger_trades("breakout", dates, signals, prices, turns)) == 1
    del prices[str(dates[11])]
    assert not trigger_trades("breakout", dates, signals, prices, turns)


@pytest.mark.parametrize("listed", [False, True])
def test_benchmark_confirmed_absence_and_listing(db, listed):
    days = [date(2025, 6, d) for d in (10, 11, 12, 13, 16, 17, 18)]
    db.add(Stock(ticker="0050", name="ETF", market="上市"))
    for i, day in enumerate((days[0], days[-1])):
        db.add(StockPriceDaily(
            id=100 + i, ticker="0050", trade_date=day,
            open=100, high=101, low=99, close=100, volume=100,
            adj_open=100, adj_high=101, adj_low=99, adj_close=100,
        ))
    db.commit()
    absent = {day: {"0050"} for day in days[1:-1]}
    requested = [days[0] - timedelta(days=1), *days] if listed else days
    with pytest.raises(DataUnavailable):
        load_benchmark(db, requested[0], days[-1], requested)
    result = load_benchmark(
        db, requested[0], days[-1], requested,
        listed_on=days[0] if listed else None, absent=absent,
    )
    assert set(result) == {str(days[0]), str(days[-1])}


@pytest.mark.parametrize("rule_id", [1, 3])
def test_process_stock_engine_and_signal_sources(monkeypatch, rule_id):
    from contextlib import nullcontext
    from unittest.mock import Mock

    from app.backtest.service import restore_rule
    from app.conditions.types import ConditionBar
    from app.research import rule_variants as module

    values = [100] * 25 + [110, 115, 120, 110, 90, 80, 85, 105, 115, 120, 90, 80, 100]
    dates = [date(2026, 1, 1) + timedelta(days=i) for i in range(len(values))]
    raw = [
        ConditionBar(d, v, v + 1, v - 15, v, volume=100)
        for d, v in zip(dates, values, strict=True)
    ]
    current = restore_rule(dict(
        id=rule_id, name="roles", logic_operator="AND", conditions=[
            dict(condition_id=c, params=p, role=r, sort_order=i)
            for i, (c, p, r) in enumerate([
                ("ma_rising", {"period": 2, "slope_lookback": 1}, "premise"),
                ("price_touch_ma", {"period": 2}, "entry"),
                ("close_below_ma_days", {"period": 2, "days": 2}, "exit"),
            ])
        ],
    ))
    start, end = dates[25], dates[-1]
    payload = simulate(current, "T", raw, [], start, end, dates)
    closed = [t for t in payload["trades"] if t["status"] == "closed"]
    assert closed
    turns = {str(d): 1e8 for d in dates}
    benchmark = {str(d): {"open": 100 + i} for i, d in enumerate(dates)}
    monkeypatch.setattr(module, "load_data", lambda *args: (raw, [], turns))
    spy = Mock(wraps=simulate)
    monkeypatch.setattr(module, "simulate", spy)
    result = process_stock(
        nullcontext, "T", current, start, end, dates[0], dates,
        "etf", TradingCosts(), benchmark,
    )
    assert result["reason"] is None
    assert spy.call_count == (2 if rule_id == 1 else 1)
    for variant in VARIANTS[:3]:
        actual = [t for t in result["trades"] if t["variant"] == variant.name]
        assert len(actual) == len(closed)
        for a, b in zip(actual, closed, strict=True):
            assert (a["entry"], a["exit"], a["gross"]) == (
                b["entryDate"], b["exitDate"], b["returnRate"],
            )
            assert a["signal_date"] == b["entrySignalDate"]
            assert a["holding_days"] == b["holdingDays"]
            assert a["net"] == TradingCosts().net_return(b["entryPrice"], b["exitPrice"], "etf")
            assert a["excess"] == pytest.approx(
                a["net"] - (benchmark[a["exit"]]["open"] / benchmark[a["entry"]]["open"] - 1)
            )
    expected_payload = payload
    if rule_id == 1:
        legacy = rule()
        legacy.conditions[0].params = {"period": 20}
        expected_payload = simulate(legacy, "T", raw, [], start, end, dates)
        assert expected_payload["signals"] != payload["signals"]
    prices = {str(b.trade_date): b for b in raw}
    for variant in VARIANTS[3:]:
        expected = trades_for(
            "T", expected_payload["signals"], prices, turns, "etf", variant,
            TradingCosts(), benchmark, dates,
        )
        assert [t for t in result["trades"] if t["variant"] == variant.name] == expected
    assert any(t["variant"] == "原規則" for t in result["trades"])


@pytest.mark.parametrize("threshold", [1e7, 1e8])
@pytest.mark.parametrize("delta", [None, -1, 0, 1])
def test_engine_turnover_filter_uses_signal_day(threshold, delta):
    from app.research.rule_variants import engine_trades

    trade = dict(
        status="closed", entrySignalDate="2026-01-01", entryDate="2026-01-02",
        exitDate="2026-01-04", entryPrice=100, exitPrice=110, returnRate=0.1, holdingDays=2,
    )
    turn = None if delta is None else threshold + delta
    payload = {"trades": [trade, {"status": "open"}, {"status": "unfilled"}]}
    result = engine_trades(
        "T", payload, {"2026-01-01": turn, "2026-01-02": 0}, "stock",
        Variant("engine", source="engine", min_turn=threshold), TradingCosts(), {},
    )
    assert bool(result) == (delta is not None and delta >= 0)
    if result:
        assert result[0]["signal_turnover"] == turn
        assert result[0]["excess"] is None
        assert result[0]["excess_market"] is None
        assert result[0]["excess_random"] is None


def test_engine_variant_order_and_report_definition():
    assert [(v.name, v.source, v.min_turn) for v in VARIANTS[:3]] == [
        ("現行定義", "engine", None),
        ("現行定義＋成交金額 ≥ 1,000 萬", "engine", 1e7),
        ("現行定義＋成交金額 ≥ 1 億", "engine", 1e8),
    ]
    with pytest.raises(ValueError, match="source"):
        Variant("invalid", source="unknown")
    for rule_id in (1, 3):
        report = markdown(dict(
            parameters=dict(universe="market", start="2026-01-01", end="2026-01-31",
                            rule_id=rule_id),
            universe_size=0, succeeded=0, skipped=[], benchmark_reason=None, statistics={},
        ))
        assert "現行定義＝DB 中的戰法定義" in report
        assert ("其餘變體以舊戰法二" in report) == (rule_id == 1)


def test_holding_proportions_boundaries_and_empty():
    trades = [dict(net=0, excess=None, ticker="T", holding_days=h) for h in (1, 10, 11, 20, 21)]
    result = statistics(trades)
    assert result["holding_le_10_rate"] == 2 / 5
    assert result["holding_gt_20_rate"] == 1 / 5
    assert statistics([])["holding_le_10_rate"] is None
    assert statistics([])["holding_gt_20_rate"] is None


def test_condition_override_isolated_cached_and_preserves_rule_settings(monkeypatch):
    from contextlib import nullcontext

    from app.backtest.service import rule_snapshot
    from app.research import rule_variants as module

    current = rule()
    current.logic_operator = "OR"
    current.evaluation_frequency = "weekly"
    before = rule_snapshot(current)
    conditions = (("ma_rising", {"period": 2, "slope_lookback": 1}, "premise"),)
    reordered = (("ma_rising", {"slope_lookback": 1, "period": 2}, "premise"),)
    variants = (Variant("current", source="engine"),
                Variant("changed", source="engine", conditions=conditions),
                Variant("shared", source="engine", conditions=reordered))
    calls = []

    def simulate_stub(r, *args):
        calls.append(rule_snapshot(r))
        return dict(signals=[], actualStart="2026-01-01", actualEnd="2026-01-04", trades=[dict(
            status="closed", entrySignalDate="2026-01-01", entryDate="2026-01-02",
            exitDate="2026-01-04", entryPrice=100, exitPrice=100 + len(calls),
            returnRate=len(calls) / 100, holdingDays=2)])

    monkeypatch.setattr(module, "load_data", lambda *a: ([], [], {}))
    monkeypatch.setattr(module, "simulate", simulate_stub)
    d = date(2026, 1, 1)
    result = process_stock(nullcontext, "T", current, d, d, d, [d], "stock",
                           TradingCosts(), {}, variants=variants)
    assert result["reason"] is None
    assert len(calls) == 2  # No legacy simulation for engine-only variants.
    assert [t["gross"] for t in result["trades"]] == [0.01, 0.02, 0.02]
    assert calls[1]["conditions"][0]["condition_id"] == "ma_rising"
    assert all(c["logic_operator"] == "OR" and c["evaluation_frequency"] == "weekly"
               for c in calls)
    assert rule_snapshot(current) == before


@pytest.mark.parametrize("variant_set,count", [("tuning", 9), ("distance", 4)])
def test_tuning_cli_report_and_reject_other_rule(monkeypatch, tmp_path, variant_set, count):
    import json
    from dataclasses import asdict

    from app.backtest.service import rule_snapshot
    from app.research import rule_variants as module

    seen = []

    def research_stub(args):
        variants = module.select_variants(args.variant_set, args.rule_id)
        seen.append(variants)
        return dict(
            parameters=dict(universe=args.universe, start="2026-01-01", end="2026-01-31",
                            rule_id=args.rule_id, variant_set=args.variant_set,
                            variants=[asdict(v) for v in variants], rule=rule_snapshot(rule())),
            universe_size=0, succeeded=0, skipped=[], benchmark_reason=None,
            statistics=summarize([], date(2026, 1, 1), date(2026, 1, 31), variants))

    monkeypatch.setattr(module, "run_research", research_stub)
    json_path, md_path = tmp_path / "out.json", tmp_path / "out.md"
    argv = ["--universe", "market", "--out-json", str(json_path), "--out-md", str(md_path)]
    module.main(argv + ["--variant-set", variant_set])
    variants = module.select_variants(variant_set, 1)
    assert seen == [variants]
    report = md_path.read_text()
    assert "舊戰法二" not in report and "拉回進場＝" not in report
    assert report.count("\n- ") == count
    result = json.loads(json_path.read_text())
    assert len(result["parameters"]["variants"]) == count
    for group in result["statistics"].values():
        assert list(group) == [v.name for v in variants]
    if variant_set == "distance":
        assert 'max_close_distance_pct": 0.03' in report
        for variant in variants:
            assert f"- {variant.name}：" in report
    with pytest.raises(SystemExit) as error:
        module.main(argv + ["--variant-set", variant_set, "--rule-id", "2"])
    assert error.value.code == 2
    with pytest.raises(ValueError, match="rule_id"):
        module.select_variants(variant_set, 2)
    module.main(argv)
    assert seen[-1] == VARIANTS and len(VARIANTS) == 14


def test_tuning_condition_definitions_and_order():
    from app.research.rule_variants import RULE2_TUNING

    assert [v.name for v in RULE2_TUNING] == [
        "現行", "A1 出場緩衝 2%", "A2 出場連續 3 天", "B 進場等分歧", "C 斜率 ≥ 1%",
        "A1＋B", "A1＋C", "B＋C", "A1＋B＋C"]
    assert RULE2_TUNING[0].conditions is None
    for i, variant in enumerate(RULE2_TUNING[1:], 1):
        assert variant.source == "engine"
        premise, entry, exit = variant.conditions
        assert premise == ("ma_rising", {"period": 20, "slope_lookback": 5,
                            **({"min_slope_pct": 0.01} if i in (4, 6, 7, 8) else {})}, "premise")
        assert entry == ("ma_touch_rebound" if i in (3, 5, 7, 8) else "price_touch_ma",
                         {"period": 20, "tolerance": 0.01}, "entry")
        assert exit == ("close_below_ma_days", {"period": 20, "days": 3 if i == 2 else 2,
                         **({"buffer": 0.02} if i in (1, 5, 6, 8) else {})}, "exit")


@pytest.mark.parametrize("roles", [False, True])
def test_role_replay_matches_engine_with_suspensions(roles):
    from app.backtest.service import restore_rule
    from app.conditions.types import ConditionBar
    from app.research.rule_variants import role_trades

    values = [100] * 25 + [110, 115, 120, 110, 90, 80, 85, 105, 115, 120, 90, 80, 100] * 3
    dates = [date(2026, 1, 1) + timedelta(days=i) for i in range(len(values))]
    raw = [ConditionBar(d, v, v + 1, v - 15, v, volume=0 if i in (27, 35) else 100)
           for i, (d, v) in enumerate(zip(dates, values, strict=True))]
    current = rule()
    if roles:
        current = restore_rule(dict(id=1, name="roles", logic_operator="AND", conditions=[
            dict(condition_id=c, params=p, role=r, sort_order=i)
            for i, (c, p, r) in enumerate([
                ("ma_rising", {"period": 2, "slope_lookback": 1}, "premise"),
                ("price_touch_ma", {"period": 2}, "entry"),
                ("close_below_ma_days", {"period": 2, "days": 2}, "exit"),
            ])]))
    payload = simulate(current, "T", raw, [], dates[25], dates[-1], dates)
    prices = {str(b.trade_date): b for b in adjusted_bars([b for b in raw if usable(b)], [])}
    actual = role_trades("T", payload["signals"], prices, {}, "stock", TradingCosts(), {}, dates)
    closed = [t for t in payload["trades"] if t["status"] == "closed"]
    assert len(closed) >= 2
    assert [(t["entry"], t["exit"], t["gross"], t["holding_days"]) for t in actual] == [
        (t["entryDate"], t["exitDate"], t["returnRate"], t["holdingDays"]) for t in closed]


def test_role_filter_delays_entry_but_never_blocks_exit():
    from app.research.rule_variants import role_trades

    dates, signals, prices, turns = synthetic([True] * 6)
    for i, signal in enumerate(signals):
        signal.update(premiseMet=True, entryTriggered=True, exitTriggered=i == 3)
    trades = role_trades("T", signals, prices, turns, "stock", TradingCosts(), {}, dates,
                         entry_allowed=lambda day: day == str(dates[1]))
    assert len(trades) == 1
    assert (trades[0]["signal_date"], trades[0]["entry"], trades[0]["exit"]) == tuple(
        str(dates[i]) for i in (1, 2, 4))


def test_market_filter_boundaries_history_and_no_future():
    from app.research.rule_variants import MARKET_VARIANTS, market_filters

    dates = [date(2026, 1, 1) + timedelta(days=i) for i in range(65)]
    days = list(map(str, dates))
    benchmark = {d: {"close": 100 if i < 60 else 101} for i, d in enumerate(days)}
    rising = {d: 100 + i for i, d in enumerate(days)}
    flat = dict.fromkeys(days, 100)
    stocks = {"up": rising, "flat": flat, "new": {days[-1]: 1000}}
    filters = market_filters(benchmark, stocks, dates)
    _, m1, m2, m3, both = [filters[v.name] for v in MARKET_VARIANTS]
    assert not m1[days[58]] and not m1[days[59]] and m1[days[60]]
    assert not m2[days[59]] and m2[days[60]]
    assert not any(m3.values())  # Exactly 50%, and a new listing is ineligible.
    del stocks["flat"][days[60]]  # No valid current bar: excluded from denominator.
    changed = market_filters(benchmark, stocks, dates)
    assert changed[MARKET_VARIANTS[3].name][days[60]]
    assert changed[MARKET_VARIANTS[4].name][days[60]]
    assert not both[days[60]]
    early = market_filters(benchmark, stocks, dates[:61])
    assert all(early[name][d] == changed[name][d] for name in early for d in days[:61])
    assert not changed[MARKET_VARIANTS[3].name][days[18]]
    # A calendar gap in 0050 must not shift the five-session comparison.
    del benchmark[days[59]]
    missing = market_filters(benchmark, stocks, dates)
    assert not missing[MARKET_VARIANTS[2].name][days[64]]


def test_market_worker_compact_data_and_cli(monkeypatch, tmp_path):
    from contextlib import nullcontext
    from dataclasses import asdict

    from app.conditions.types import ConditionBar
    from app.research import rule_variants as module

    dates = [date(2026, 1, 1) + timedelta(days=i) for i in range(65)]
    raw = [ConditionBar(d, 100 + i, 101 + i, 99 + i, 100 + i, volume=100)
           for i, d in enumerate(dates)]
    monkeypatch.setattr(module, "load_data", lambda *a: (raw, [], {}))
    result = process_stock(nullcontext, "T", rule(), dates[25], dates[-1], dates[0], dates,
                           "stock", TradingCosts(), {}, variants=module.MARKET_VARIANTS)
    assert result["reason"] is None
    assert result["trades"] == []
    assert len(result["closes"]) == 65
    assert set(result["signals"][0]) == {
        "date", "isMet", "premiseMet", "entryTriggered", "exitTriggered"}
    assert all(isinstance(v, (int, float)) for v in result["opens"].values())

    def research_stub(args):
        variants = module.select_variants(args.variant_set, args.rule_id)
        filters = module.market_filters({}, {}, dates)
        return dict(parameters=dict(universe=args.universe, start=str(dates[0]),
                                    end=str(dates[-1]), rule_id=args.rule_id,
                                    variant_set=args.variant_set,
                                    variants=[asdict(v) for v in variants]),
                    universe_size=0, succeeded=0, skipped=[], benchmark_reason=None,
                    statistics=summarize([], dates[0], dates[-1], variants),
                    entry_allowance=module.entry_allowance(filters, dates, dates[0], dates[-1]))

    monkeypatch.setattr(module, "run_research", research_stub)
    argv = ["--universe", "market", "--variant-set", "market", "--out-json",
            str(tmp_path / "out.json"), "--out-md", str(tmp_path / "out.md")]
    module.main(argv)
    report = (tmp_path / "out.md").read_text()
    assert "允許進場比例" in report and "100.0%" in report
    assert "舊戰法二" not in report and "拉回進場＝" not in report
    assert len(module.select_variants("market", 1)) == 5
    for variant in module.MARKET_VARIANTS:
        assert variant.name in report
        assert variant.conditions == module._tuning_conditions(buffer=0.02, rebound=True)
    with pytest.raises(SystemExit) as error:
        module.main(argv + ["--rule-id", "2"])
    assert error.value.code == 2
    with pytest.raises(ValueError, match="rule_id"):
        module.select_variants("market", 2)


def test_market_main_thread_replays_after_collecting_pool(monkeypatch):
    from contextlib import nullcontext
    from unittest.mock import Mock

    from app.research import rule_variants as module

    dates, signals, prices, turns = synthetic([True, True, True, True, False, False])
    for i, signal in enumerate(signals):
        signal.update(premiseMet=True, entryTriggered=True, exitTriggered=i == 4)
    db = Mock()
    db.execute.return_value.all.return_value = []
    db.scalars.return_value = []
    monkeypatch.setattr(module, "load_universe", lambda *a: ["T"])
    monkeypatch.setattr(module, "chosen_rules", lambda *a: [rule()])
    monkeypatch.setattr(module, "load_calendar", lambda *a: dates)
    monkeypatch.setattr(module, "load_benchmark", lambda *a: {})
    collected = []

    def worker(*args):
        collected.append(True)
        return dict(ticker="T", reason=None, trades=[], signals=signals, turnover=turns,
                    opens={d: b.open for d, b in prices.items()},
                    closes=dict.fromkeys(prices, 100))

    def filters(benchmark, closes, calendar, index_benchmark=None, index_dates=None):
        assert collected and closes == {"T": dict.fromkeys(prices, 100)}
        return {v.name: {str(d): i >= j for i, d in enumerate(calendar)}
                for j, v in enumerate(module.MARKET_VARIANTS)}

    monkeypatch.setattr(module, "process_stock", worker)
    monkeypatch.setattr(module, "market_filters", filters)
    result = module.run_research(SimpleNamespace(
        variant_set="market", rule_id=1, start=dates[0], end=dates[-1],
        years=1, universe="market", workers=1), factory=lambda: nullcontext(db))
    assert len(result["trades"]) == 4  # The last variant remains open at the end.
    assert [t["signal_date"] for t in result["trades"]] == list(map(str, dates[:4]))
    assert all(t["exit"] == str(dates[-1]) for t in result["trades"])
    assert result["entry_allowance"]["2026"]["無濾網"] == 1
    assert result["entry_allowance"]["2025"]["無濾網"] is None
    assert result["stocks"] == [{"ticker": "T", "reason": None}]


def test_market_filters_use_longer_index_history_for_m1():
    # Regression: with only the study warm-up, the 60-day mean did not exist early in the
    # study and M1 blocked every entry for lack of data, flattering the first half-year.
    from datetime import date, timedelta

    from app.research.rule_variants import market_filters

    index_dates = [date(2024, 1, 1) + timedelta(days=i) for i in range(100)]
    study_dates = index_dates[80:]
    index_benchmark = {d.isoformat(): {"open": 100 + i, "close": 100 + i}
                       for i, d in enumerate(index_dates)}
    study_benchmark = {d: v for d, v in index_benchmark.items() if d >= study_dates[0].isoformat()}
    short = market_filters(study_benchmark, {}, study_dates)
    long = market_filters(study_benchmark, {}, study_dates, index_benchmark, index_dates)
    m1 = next(name for name in long if name.startswith("M1"))
    first = study_dates[0].isoformat()
    assert short[m1][first] is False
    assert long[m1][first] is True


def test_distance_condition_definitions_and_order():
    from app.research.rule_variants import DISTANCE_VARIANTS, RULE2_TUNING, select_variants

    variants = select_variants("distance", 1)
    assert variants == DISTANCE_VARIANTS
    assert [v.name for v in variants] == ["無限制", "≤ 2%", "≤ 3%", "≤ 5%"]
    assert variants[0].conditions == RULE2_TUNING[5].conditions
    for variant, distance in zip(variants, (None, 0.02, 0.03, 0.05), strict=True):
        assert variant.source == "engine"
        premise, entry, exit = variant.conditions
        assert premise == ("ma_rising", {"period": 20, "slope_lookback": 5}, "premise")
        assert entry == ("ma_touch_rebound", {
            "period": 20, "tolerance": 0.01,
            **({"max_close_distance_pct": distance} if distance is not None else {}),
        }, "entry")
        assert exit == ("close_below_ma_days", {"period": 20, "days": 2, "buffer": 0.02}, "exit")


def test_distance_parameter_only_applies_to_rebound():
    from app.research.rule_variants import _tuning_conditions

    assert _tuning_conditions(max_distance=0.03) == _tuning_conditions()
