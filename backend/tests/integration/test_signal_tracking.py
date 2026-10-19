"""Publication/returns/API integration on isolated SQL, with no real external traffic."""

# ruff: noqa: F811 -- shared pytest fixtures
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select
from test_market_scan import DAY, NOW, factory, manager, success  # noqa: F401

from app.backtest.models import BacktestCalendarMonth
from app.core.config import Settings
from app.core.dependencies import get_db
from app.main import app
from app.market_data.models import Stock, StockPriceDaily
from app.market_scan.models import (
    MarketInstrument,
    ScanCandidate,
    ScanPublication,
    ScanTask,
    SignalHistory,
    SignalReturn,
)
from app.market_scan.signal_tracking import backfill, record_signals
from app.trading_costs import TradingCosts

DAYS = [date(2026, 10, d) for d in (12, 13, 14, 15, 16, 19, 20)]


def signal(db, ticker="1", day=DAY, rid=1, horizons=(1, 5, 10, 20), older=False):
    row = SignalHistory(
        signal_date=day,
        ticker=ticker,
        stock_name="股票",
        rule_id=rid,
        rule_name="布林",
        kind="stock",
        price_date=day,
        older_quote=older,
        close=100,
        volume=1000,
        turnover=100000,
        indicators={},
        source="manual",
        first_batch_id="first",
        last_batch_id="first",
        created_at=datetime.utcnow(),
        last_seen_at=datetime.utcnow(),
        cost_snapshot=TradingCosts().snapshot(),
    )
    db.add(row)
    db.flush()
    db.add_all(
        [
            SignalReturn(signal_id=row.id, horizon=h, status="pending", values_json={})
            for h in horizons
        ]
    )
    return row.id


def bar(ticker, day, open=100, close=110, low=90, volume=1000):
    return StockPriceDaily(
        ticker=ticker,
        trade_date=day,
        open=open,
        high=max(open, close) + 5,
        low=low,
        close=close,
        volume=volume,
        turnover=10000,
        adj_open=open,
        adj_high=max(open, close) + 5,
        adj_low=low,
        adj_close=close,
    )


def prepare(db, days=DAYS):
    db.add(Stock(ticker="0050", name="元大台灣50", market="上市"))
    db.add(
        BacktestCalendarMonth(
            month="2026-10", checked_on=DAYS[-1], dates=[d.isoformat() for d in DAYS]
        )
    )
    db.add_all([bar("0050", d, open=50, close=51, low=49) for d in days])
    db.flush()


def test_first_snapshot_same_day_repeat_and_nonmatch_history_survives(factory):
    job = manager(factory)
    first = job.start([1], now=NOW)
    job.close()
    with factory() as db:
        original = db.scalar(select(SignalHistory).where(SignalHistory.ticker == "1"))
        price = float(original.close)
        created = original.created_at
        assert db.scalar(select(func.count()).select_from(SignalHistory)) == 2
        assert db.scalar(select(func.count()).select_from(SignalReturn)) == 8

    def modified(*args):
        outcome = success(*args)
        for candidate in outcome.candidates:
            candidate["close"] = 9999
        return outcome

    job.worker = modified
    second = job.start([1], now=NOW)
    job.close()
    with factory() as db:
        row = db.scalar(select(SignalHistory).where(SignalHistory.ticker == "1"))
        assert float(row.close) == price and row.created_at == created
        assert row.first_batch_id == first and row.last_batch_id == second
        assert db.scalar(select(func.count()).select_from(SignalHistory)) == 2
    from app.market_scan.worker import Outcome

    job.worker = lambda *args: Outcome(args[1][0], rules={1: ("normal", None)})
    job.start([1], now=NOW)
    job.close()
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(ScanCandidate)) == 0
        assert db.scalar(select(func.count()).select_from(SignalHistory)) == 2


def test_only_normal_and_publication_rollback_includes_history(factory, monkeypatch):
    with factory() as db:
        # Non-normal snapshots are ignored even if accidentally present in candidates.
        record_signals(
            db,
            "bad",
            [SimpleNamespace(candidates=[{"status": "stale"}])],
            {"baseline": DAY.isoformat(), "source": "manual"},
        )
        db.commit()
        assert db.scalar(select(func.count()).select_from(SignalHistory)) == 0
    import app.market_scan.signal_tracking as tracking

    original = tracking.record_signals

    def fail(*args):
        original(*args)
        raise RuntimeError("rollback after signal insert")

    monkeypatch.setattr(tracking, "record_signals", fail)
    job = manager(factory)
    job.start([1], now=NOW)
    job.close()
    with factory() as db:
        assert db.get(ScanTask, "scan").status == "failed"
        assert db.scalar(select(func.count()).select_from(SignalHistory)) == 0
        assert db.scalar(select(func.count()).select_from(SignalReturn)) == 0
        assert db.scalar(select(func.count()).select_from(ScanCandidate)) == 0
        assert db.get(ScanPublication, 1) is None


def test_next_day_close_pending_and_completed_not_recomputed(factory, monkeypatch):
    network = Mock(side_effect=AssertionError("no HTTP allowed"))
    monkeypatch.setattr("httpx.get", network)
    with factory() as db:
        sid = signal(db)
        prepare(db)
        db.add_all([bar("1", d) for d in DAYS[1:]])
        db.commit()
    backfill(factory, DAYS[1])
    with factory() as db:
        first = db.get(SignalReturn, (sid, 1))
        assert first.status == "pending"
        assert first.reason == "觀察期尚未到期"
        assert first.values_json == {}
    backfill(factory, DAYS[2])
    with factory() as db:
        first = db.get(SignalReturn, (sid, 1))
        assert first.status == "completed"
        values = first.values_json
        assert values["entryDate"] == DAYS[1].isoformat()
        assert values["dueDate"] == values["valuationDate"] == DAYS[2].isoformat()
        assert values["grossReturn"] == pytest.approx(0.1)
        assert values["netReturn"] == pytest.approx(TradingCosts().net_return(100, 110))
        assert values["benchmarkReturn"] == pytest.approx(0.02)
        assert values["excessReturn"] == pytest.approx(values["netReturn"] - 0.02)
        assert values["maxAdverseReturn"] == pytest.approx(-0.1)
        assert db.get(SignalReturn, (sid, 5)).status == "pending"
        assert db.get(SignalReturn, (sid, 5)).values_json == {}
        b = db.scalar(
            select(StockPriceDaily).where(
                StockPriceDaily.ticker == "1", StockPriceDaily.trade_date == DAYS[2]
            )
        )
        b.adj_close = 105
        db.commit()
    backfill(factory, DAYS[-1])
    with factory() as db:
        assert db.get(SignalReturn, (sid, 1)).values_json == values
        assert db.get(SignalReturn, (sid, 5)).status == "completed"
        assert db.get(SignalReturn, (sid, 10)).status == "pending"
    network.assert_not_called()


def test_suspension_entry_delays_and_exit_uses_previous_close(factory):
    with factory() as db:
        sid = signal(db, horizons=(1, 3))
        prepare(db)
        db.add(bar("1", DAYS[1], volume=0))
        db.add(bar("1", DAYS[2], open=100, close=102))
        db.add(bar("1", DAYS[3], open=103, close=104))
        db.add(bar("1", DAYS[4], volume=0))
        db.commit()
    backfill(factory, DAYS[5])
    with factory() as db:
        values = db.get(SignalReturn, (sid, 3)).values_json
        assert values["entryDate"] == DAYS[2].isoformat()
        assert values["dueDate"] == DAYS[5].isoformat()
        assert values["valuationDate"] == DAYS[3].isoformat()
        assert values["grossReturn"] == pytest.approx(0.04)


def test_benchmark_missing_can_recover_and_delisted_unavailable(factory):
    with factory() as db:
        sid = signal(db)
        sid2 = signal(db, ticker="2")
        prepare(db, days=[])
        db.add(bar("1", DAYS[1]))
        db.get(MarketInstrument, "2").active = False
        db.commit()
    backfill(factory, DAYS[2])
    with factory() as db:
        r = db.get(SignalReturn, (sid, 1))
        assert r.status == "unavailable" and "0050" in r.reason
        assert db.get(SignalReturn, (sid2, 1)).status == "unavailable"
        db.add_all([bar("0050", d, open=50, close=51, low=49) for d in DAYS[1:3]])
        db.commit()
    backfill(factory, DAYS[2])
    with factory() as db:
        assert db.get(SignalReturn, (sid, 1)).status == "completed"


def test_backfill_failure_keeps_published_results(factory, monkeypatch):
    monkeypatch.setattr("app.market_scan.service.backfill", Mock(side_effect=RuntimeError))
    job = manager(factory)
    job.start([1], now=NOW)
    job.close()
    with factory() as db:
        assert db.get(ScanTask, "scan").status == "completed"
        assert any("績效回填失敗" in w for w in db.get(ScanTask, "scan").warnings)
        assert db.get(ScanPublication, 1) is not None
        assert db.scalar(select(func.count()).select_from(SignalHistory)) == 2


def test_backfill_batches_ohlc_query_not_per_signal(factory):
    with factory() as db:
        prepare(db)
        for rid in range(1, 41):
            signal(db, rid=rid, horizons=(1,))
        db.add(bar("1", DAYS[1]))
        db.commit()
    queries = []

    def capture(conn, cursor, statement, *args):
        if statement.lstrip().upper().startswith("SELECT") and "stock_price_daily" in statement:
            queries.append(statement)

    engine = factory.kw["bind"]
    event.listen(engine, "before_cursor_execute", capture)
    try:
        backfill(factory, DAYS[1])
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert len(queries) == 1


def test_api_empty_samples_filters_pagination_and_summary(factory):
    with factory() as db:
        sid = signal(db)
        signal(db, ticker="2", rid=2, older=True)
        db.commit()

    def override():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override
    try:
        with TestClient(app) as client:
            groups = client.get("/market-scan/signal-performance?ruleId=1").json()["groups"]
            assert len(groups) == 4
            assert all(
                g["sampleCount"] == 0 and g["averageNetReturn"] is None and g["sampleInsufficient"]
                for g in groups
            )
            detail = client.get("/market-scan/signals?excludeOlderQuote=true&pageSize=1").json()
            assert detail["total"] == 1 and detail["items"][0]["ticker"] == "1"
            assert detail["items"][0]["returns"][0]["netReturn"] is None
            assert client.get("/market-scan/signals?pageSize=201").status_code == 422
            assert (
                client.get("/market-scan/signals?from=2026-10-20&to=2026-10-01").status_code == 422
            )
            assert client.get("/market-scan/signals?minTurnover=200000").json()["total"] == 0
            assert (
                client.get("/market-scan/signals?ticker=2&signalDate=2026-10-12").json()["total"]
                == 1
            )
            with factory() as db:
                r = db.get(SignalReturn, (sid, 1))
                r.status = "completed"
                r.values_json = dict(netReturn=0.1, excessReturn=0.03, maxAdverseReturn=-0.05)
                db.commit()
            group = client.get("/market-scan/signal-performance?ruleId=1").json()["groups"][0]
            assert group["sampleCount"] == 1 and group["sampleInsufficient"]
            assert group["winRate"] == 1 and group["medianNetReturn"] == 0.1
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize("value", ["", "0,1", "1,61", "1,x", "1,2.5"])
def test_horizons_validation(value):
    with pytest.raises(ValueError):
        Settings(signal_tracking_horizons=value)


def test_horizon_one_exits_next_market_session_after_weekend(factory):
    with factory() as db:
        sid = signal(db, day=DAYS[3], horizons=(1,))
        prepare(db)
        db.add(bar("1", DAYS[4], open=100, close=102, low=85))
        db.add(bar("1", DAYS[5], open=103, close=120, low=95))
        db.add(bar("1", DAYS[6], close=130, low=70))
        db.commit()
    backfill(factory, DAYS[6])
    with factory() as db:
        result = db.get(SignalReturn, (sid, 1))
        assert result.status == "completed"
        values = result.values_json
        assert values["entryDate"] == "2026-10-16"
        assert values["dueDate"] == values["valuationDate"] == "2026-10-19"
        assert values["exitPrice"] == 120
        assert values["grossReturn"] == pytest.approx(0.2)
        assert values["maxAdverseReturn"] == pytest.approx(-0.15)


@pytest.mark.parametrize("benchmark_missing", [False, True])
def test_incomplete_calendar_only_marks_due_returns_unavailable(factory, benchmark_missing):
    with factory() as db:
        sid = signal(db, horizons=(1, 5))
        waiting_sid = signal(db, ticker="2", horizons=(1,))
        prepare(db, days=[] if benchmark_missing else DAYS)
        db.add_all([bar("1", d) for d in DAYS[1:3]])
        db.get(BacktestCalendarMonth, "2026-10").checked_on = DAYS[1]
        db.commit()
    backfill(factory, DAYS[2])
    with factory() as db:
        due = db.get(SignalReturn, (sid, 1))
        assert due.status == "unavailable"
        assert due.reason == "交易日曆不完整"
        assert due.values_json == {}
        pending = db.get(SignalReturn, (sid, 5))
        assert pending.status == "pending"
        assert pending.reason == "觀察期尚未到期"
        assert pending.values_json == {}
        waiting = db.get(SignalReturn, (waiting_sid, 1))
        assert waiting.status == "pending"
        assert waiting.reason == "等待下一有效交易日進場"
        assert waiting.values_json == {}
        db.get(BacktestCalendarMonth, "2026-10").checked_on = DAYS[-1]
        if benchmark_missing:
            db.add_all([bar("0050", d, open=50, close=51, low=49) for d in DAYS[1:3]])
        db.commit()
    backfill(factory, DAYS[2])
    with factory() as db:
        assert db.get(SignalReturn, (sid, 1)).status == "completed"
        assert db.get(SignalReturn, (sid, 5)).status == "pending"


def test_missing_calendar_keeps_unknown_due_dates_pending(factory):
    with factory() as db:
        sid = signal(db, horizons=(1, 5))
        db.add(bar("1", DAYS[1]))
        db.commit()
    backfill(factory, DAYS[-1])
    with factory() as db:
        for horizon in (1, 5):
            result = db.get(SignalReturn, (sid, horizon))
            assert result.status == "pending"
            assert result.reason == "等待下一有效交易日進場"
            assert result.values_json == {}
