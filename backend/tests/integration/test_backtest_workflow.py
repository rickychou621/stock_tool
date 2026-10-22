import copy
from datetime import UTC, date, datetime, timedelta
from threading import Barrier, Event, Lock
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import BigInteger, Integer, MetaData, create_engine, select
from sqlalchemy.orm import sessionmaker

from app.backtest.data import load_trading_dates, prepare_data
from app.backtest.models import BacktestResult, BacktestTask
from app.backtest.service import BacktestBusy, BacktestManager, read_report
from app.backtest.simulation import metrics
from app.core.db import Base
from app.core.dependencies import get_db
from app.main import app
from app.market_data.models import Stock, StockPriceDaily
from app.market_data.service import MarketDataService
from app.rules.models import WatchRule, WatchRuleCondition
from app.watchlist.models import HoldingsWatchlist

DAY = date(2026, 10, 12)
NOW = datetime(2026, 10, 13, 8, tzinfo=ZoneInfo("Asia/Taipei"))
DATES = [DAY - timedelta(days=i) for i in reversed(range(5))]


@pytest.fixture
def factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'backtest.db'}")
    metadata = MetaData()
    for table in Base.metadata.sorted_tables:
        table.to_metadata(metadata)
    for table in metadata.tables.values():
        for column in table.columns:
            if isinstance(column.type, BigInteger):
                column.type = Integer()
    metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    with sessions() as db:
        for i in range(1, 3):
            db.add(Stock(ticker=str(i), name=f"Stock {i}", market="上市"))
            db.add(HoldingsWatchlist(ticker=str(i)))
        db.add(
            WatchRule(
                id=1,
                name="布林",
                is_enabled=True,
                logic_operator="AND",
                conditions=[
                    WatchRuleCondition(
                        condition_id="bollinger_mid_up", params={"period": 2, "slope_lookback": 1}
                    )
                ],
            )
        )
        db.commit()
    yield sessions
    engine.dispose()


def payload(ticker="1", rate=0.1):
    trades = [
        dict(
            ticker=ticker,
            status="closed",
            entryDate="2026-10-08",
            exitDate="2026-10-12",
            returnRate=rate,
            pendingSide=None,
        )
    ]
    return dict(
        actualStart="2026-10-08",
        actualEnd="2026-10-12",
        trades=trades,
        signals=[],
        metrics=metrics(trades),
        definition={},
        priceBasisDate="2026-10-12",
    )


def success(sessions, ticker, snapshots, *args):
    result = payload(ticker)
    result["definition"] = snapshots[0]
    return [(1, "布林", result)]


def make_manager(factory, worker=success):
    return BacktestManager(
        factory, calendar=lambda *args: DATES, worker=worker, benchmark_loader=lambda *args: {}
    )


def test_partial_failure_includes_stale_and_snapshot_is_atomic(factory):
    manager = make_manager(factory)
    first = manager.start([1], now=NOW)
    manager.close()
    with factory() as db:
        old = copy.deepcopy(
            db.scalar(select(BacktestResult).where(BacktestResult.ticker == "2")).payload
        )
        assert read_report(db)["overall"][0]["metrics"]["tradeCount"] == 2

    def fail_one(sessions, ticker, *args):
        if ticker == "2":
            # A commit failure must not leave a partially overwritten stock result.
            bad = payload(ticker)
            bad["not_serializable"] = object()
            return [(1, "布林", bad)]
        return success(sessions, ticker, *args)

    manager.worker = fail_one
    second = manager.start([1], now=NOW)
    manager.close()
    assert first != second
    with factory() as db:
        report = read_report(db)
        assert report["task"]["status"] == "partial_failure"
        assert report["task"]["succeeded"] == report["task"]["failed"] == 1
        assert report["overall"][0]["stockCount"] == 2
        assert report["overall"][0]["metrics"]["tradeCount"] == 2
        assert report["overall"][0]["stale"] is True
        assert report["staleInfo"] == dict(reason="data", changedAt=None, ruleIds=[1])
        stale = db.scalar(select(BacktestResult).where(BacktestResult.ticker == "2"))
        assert stale.stale and stale.payload == old and stale.batch_id == first
        assert len(list(db.scalars(select(BacktestTask)))) == 1


def test_one_job_and_three_workers_independent_sessions(factory):
    with factory() as db:
        for i in range(3, 7):
            db.add(Stock(ticker=str(i), name=str(i), market="上市"))
            db.add(HoldingsWatchlist(ticker=str(i)))
        db.commit()
    barrier, lock, release, entered = Barrier(3), Lock(), Event(), Event()
    active = peak = 0
    seen = []

    def worker(sessions, ticker, *args):
        nonlocal active, peak
        with sessions() as db:
            with lock:
                active += 1
                peak = max(peak, active)
                seen.append(db)
            entered.set()
            assert release.wait(5)
            barrier.wait(5)
            with lock:
                active -= 1
        if ticker == "2":
            raise RuntimeError("isolated error")
        return success(sessions, ticker, *args)

    manager = make_manager(factory, worker)
    try:
        manager.start([1], now=NOW)
        assert entered.wait(5)
        other = make_manager(factory)
        with pytest.raises(BacktestBusy):
            other.start([1], now=NOW)
        other.recover()  # Live job must not be incorrectly labelled interrupted.
        with factory() as db:
            assert db.get(BacktestTask, 1).status == "running"
    finally:
        release.set()
        manager.close()
    assert peak == 3
    assert len({id(db) for db in seen}) == 6
    with factory() as db:
        assert read_report(db)["task"]["succeeded"] == 5


def test_restart_marks_interrupted_and_keeps_results(factory):
    manager = make_manager(factory)
    manager.start([1], now=NOW)
    manager.close()
    with factory() as db:
        db.get(BacktestTask, 1).status = "running"
        before = [copy.deepcopy(r.payload) for r in db.scalars(select(BacktestResult))]
        db.commit()
    fresh = make_manager(factory)
    fresh.recover()
    with factory() as db:
        assert db.get(BacktestTask, 1).status == "interrupted"
        assert [r.payload for r in db.scalars(select(BacktestResult))] == before
    fresh.start([1], now=NOW)
    fresh.close()


def add_bars(db, ticker, days):
    for day in days:
        db.add(
            StockPriceDaily(
                ticker=ticker,
                trade_date=day,
                open=10,
                high=12,
                low=9,
                close=11,
                volume=100,
                adj_open=10,
                adj_high=12,
                adj_low=9,
                adj_close=11,
            )
        )
    db.commit()


def test_db_first_and_only_missing_data_triggers_sync(factory, monkeypatch):
    sync = Mock()
    monkeypatch.setattr(MarketDataService, "sync_daily_prices", sync)
    with factory() as db:
        add_bars(db, "1", DATES)
        raw, _ = prepare_data(db, "1", DATES[0], DAY, DATES)
        assert len(raw) == 5
        sync.assert_not_called()
        add_bars(db, "2", DATES[1:])

        def supplement(ticker, days):
            add_bars(db, ticker, DATES[:1])
            return 5

        sync.side_effect = supplement
        raw, _ = prepare_data(db, "2", DATES[0], DAY, DATES)
        assert len(raw) == 5
        assert sync.call_count == 1
        prepare_data(db, "2", DATES[0], DAY, DATES)
        assert sync.call_count == 1


def test_new_listing_and_suspension_source_coverage_prevents_repeated_fetch(factory, monkeypatch):
    with factory() as db:

        def supplement(ticker, days):
            add_bars(db, ticker, DATES[2:])
            return 3

        sync = Mock(side_effect=supplement)
        monkeypatch.setattr(MarketDataService, "sync_daily_prices", sync)
        for _ in range(2):
            raw, _ = prepare_data(db, "1", DATES[0], DAY, DATES)
            assert len(raw) == 3
        assert sync.call_count == 1


def test_calendar_caches_complete_months_and_excludes_non_sessions(factory, respx_mock):
    route = respx_mock.get("https://www.twse.com.tw/exchangeReport/FMTQIK").mock(
        return_value=httpx.Response(
            200, json={"stat": "OK", "data": [["115/01/05"], ["115/01/06"]]}
        )
    )
    assert load_trading_dates(factory, date(2026, 1, 1), date(2026, 1, 31)) == [
        date(2026, 1, 5),
        date(2026, 1, 6),
    ]
    load_trading_dates(factory, date(2026, 1, 1), date(2026, 1, 31))
    assert route.call_count == 1


def test_api_reports_empty_progress_and_details_version(factory, monkeypatch):
    release = Event()

    def waiting_worker(*args):
        assert release.wait(5)
        return success(*args)

    manager = make_manager(factory, waiting_worker)
    monkeypatch.setattr("app.backtest.router.manager", manager)

    def dependency():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = dependency
    try:
        with TestClient(app) as client:
            assert client.get("/backtests/latest").json()["task"] is None
            assert client.post("/backtests", json={"ruleIds": []}).status_code == 422
            assert client.post("/backtests", json={"ruleIds": [1]}).status_code == 202
            assert client.post("/backtests", json={"ruleIds": [1]}).status_code == 409
            release.set()
            manager.close()
            report = client.get("/backtests/latest").json()
            assert report["task"]["completed"] == 2
            item = report["stocks"][0]
            assert (
                client.get(f"/backtests/results/{item['id']}?expectedBatchId=old").status_code
                == 409
            )
            detail = client.get(f"/backtests/results/{item['id']}").json()
            assert detail["tradeTotal"] == 1
    finally:
        release.set()
        manager.close()
        app.dependency_overrides.clear()


def test_batch_data_source_error_keeps_previous_results(factory):
    manager = make_manager(factory)
    manager.start([1], now=NOW)
    manager.close()
    manager.calendar = Mock(side_effect=RuntimeError("交易日期服務失敗"))
    manager.start([1], now=NOW)
    manager.close()
    with factory() as db:
        report = read_report(db)
        assert report["task"]["status"] == "failed"
        assert report["overall"][0]["stockCount"] == 2
        assert report["overall"][0]["stale"] is True
        assert report["staleInfo"] == dict(reason="data", changedAt=None, ruleIds=[1])
        assert all(s["stale"] for s in report["stocks"])


def test_current_month_cache_refreshes_when_requested_end_advances(
    factory, respx_mock, monkeypatch
):
    monkeypatch.setattr("app.backtest.data.taipei_today", lambda: date(2026, 10, 13))
    route = respx_mock.get("https://www.twse.com.tw/exchangeReport/FMTQIK").mock(
        return_value=httpx.Response(200, json={"stat": "OK", "data": [["115/10/12"]]})
    )
    assert load_trading_dates(factory, DAY, DAY) == [DAY]
    route.mock(
        return_value=httpx.Response(
            200, json={"stat": "OK", "data": [["115/10/12"], ["115/10/13"]]}
        )
    )
    assert load_trading_dates(factory, DAY, date(2026, 10, 13))[-1] == date(2026, 10, 13)
    assert route.call_count == 2


@pytest.fixture(autouse=True)
def isolate_market_event_http(monkeypatch):
    for method in ("price_events", "tpex_price_events"):
        monkeypatch.setattr(f"app.data_source.twse_client.TwseBatchClient.{method}", lambda *a: [])
    monkeypatch.setattr(
        "app.data_source.finmind_client.FinMindClient.get_price_events", lambda *a, **kw: []
    )


def test_second_backtest_skips_all_event_sources_and_includes_0050(factory, monkeypatch):
    from app.data_source.finmind_client import FinMindClient
    from app.data_source.twse_client import TwseBatchClient
    from app.market_data.models import StockPriceEvent

    split = Mock(
        return_value=[
            dict(
                ticker="0050",
                event_date=DAY,
                event_type="split",
                before_close=100,
                reference_price=25,
                source="finmind_split",
            )
        ]
    )
    twse, tpex = Mock(return_value=[]), Mock(return_value=[])
    monkeypatch.setattr(FinMindClient, "get_price_events", split)
    monkeypatch.setattr(TwseBatchClient, "price_events", twse)
    monkeypatch.setattr(TwseBatchClient, "tpex_price_events", tpex)
    manager = make_manager(factory)
    manager.start([1], now=NOW)
    manager.close()
    counts = split.call_count, twse.call_count, tpex.call_count
    assert counts == (1, 1, 1)
    manager.start([1], now=NOW)
    manager.close()
    assert (split.call_count, twse.call_count, tpex.call_count) == counts
    with factory() as db:
        assert db.scalar(select(StockPriceEvent.ticker)) == "0050"
        assert db.get(BacktestTask, 1).errors == []


def test_event_failure_visible_in_backtest_errors(factory, monkeypatch):
    monkeypatch.setattr(
        "app.data_source.finmind_client.FinMindClient.get_price_events",
        Mock(side_effect=RuntimeError("secret-token")),
    )
    manager = make_manager(factory)
    manager.start([1], now=NOW)
    manager.close()
    with factory() as db:
        errors = db.get(BacktestTask, 1).errors
        assert any("FinMind split" in e["reason"] for e in errors)
        assert "secret-token" not in str(errors)


@pytest.mark.parametrize("change", ["missing", "role", "frequency", "same"])
def test_definition_fingerprint_persisted_and_report_includes_changed(factory, change):
    from app.backtest.service import definition_fingerprint, rule_snapshot

    manager = make_manager(factory)
    manager.start([1], now=NOW)
    manager.close()
    with factory() as db:
        rows = list(db.scalars(select(BacktestResult)))
        rule = db.get(WatchRule, 1)
        expected = definition_fingerprint(rule_snapshot(rule))
        assert all(r.summary["definitionFingerprint"] == expected for r in rows)
        if change == "missing":
            for row in rows:
                row.summary = {k: v for k, v in row.summary.items()
                               if k != "definitionFingerprint"}
        elif change == "role":
            rule.conditions[0].role = "exit"
        elif change == "frequency":
            rule.evaluation_frequency = "weekly"
        db.commit()
    with factory() as db:
        report = read_report(db)
        assert all(s["needsRerun"] == (change != "same") for s in report["stocks"])
        assert report["overall"][0]["stockCount"] == len(report["stocks"]) == 2
        assert report["overall"][0]["stale"] == (change != "same")
        if change == "same":
            assert report["staleInfo"] is None
            assert report["overall"][0]["stockCount"] == 2
            assert all("rerunReason" not in s for s in report["stocks"])
        else:
            assert report["staleInfo"] == dict(
                reason="definition",
                changedAt=db.get(WatchRule, 1).updated_at.replace(tzinfo=UTC).isoformat(),
                ruleIds=[1],
            )
            assert all(s["rerunReason"] == "戰法定義已變更，需重新回測"
                       for s in report["stocks"])


def test_report_rule_queries_do_not_grow_with_result_count(factory):
    from sqlalchemy import event

    manager = make_manager(factory)
    manager.start([1], now=NOW)
    manager.close()

    def queries():
        statements = []

        def record(conn, cursor, statement, parameters, context, executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(statement)

        engine = factory.kw["bind"]
        event.listen(engine, "before_cursor_execute", record)
        try:
            with factory() as db:
                read_report(db)
        finally:
            event.remove(engine, "before_cursor_execute", record)
        assert not any("backtest_results.payload" in sql for sql in statements)
        return len(statements)

    before = queries()
    with factory() as db:
        task = db.get(BacktestTask, 1)
        source = db.scalar(select(BacktestResult))
        for rule_id in range(2, 12):
            db.add(WatchRule(id=rule_id, name=str(rule_id), conditions=[
                WatchRuleCondition(condition_id="ma_rising", params={"period": 20})
            ]))
            db.add(BacktestResult(
                ticker="1", rule_id=rule_id, rule_name=str(rule_id), stock_name="Stock 1",
                batch_id=task.batch_id, stale=False, calculated_at=source.calculated_at,
                summary=copy.deepcopy(source.summary), payload=copy.deepcopy(source.payload),
            ))
        task.rule_ids = list(range(1, 12))
        db.commit()
    assert queries() == before


def test_report_legacy_results_excluded_from_overall(factory):
    manager = make_manager(factory)
    manager.start([1], now=NOW)
    manager.close()
    with factory() as db:
        for row in db.scalars(select(BacktestResult)):
            row.summary = {k: v for k, v in row.summary.items() if k != "schemaVersion"}
        db.commit()
        report = read_report(db)
        assert len(report["stocks"]) == 2
        assert all(s["needsRerun"] for s in report["stocks"])
        assert report["overall"] == []
        assert report["staleInfo"] == dict(reason="data", changedAt=None, ruleIds=[1])


def test_report_without_task_has_no_stale_info(factory):
    with factory() as db:
        assert read_report(db) == dict(task=None, stocks=[], overall=[], staleInfo=None)


def test_stale_info_prioritizes_definition_and_latest_changed_rule(factory):
    manager = make_manager(factory)
    manager.start([1], now=NOW)
    manager.close()
    with factory() as db:
        task = db.get(BacktestTask, 1)
        source = db.scalar(select(BacktestResult))
        for rule_id, updated_at in [
            (3, datetime(2026, 10, 20, 1)),
            (2, datetime(2026, 10, 21, 2)),
        ]:
            db.add(WatchRule(id=rule_id, name=str(rule_id), updated_at=updated_at))
            db.add(BacktestResult(
                ticker="1", rule_id=rule_id, rule_name=str(rule_id), stock_name="Stock 1",
                batch_id=task.batch_id, stale=False, calculated_at=source.calculated_at,
                summary=copy.deepcopy(source.summary), payload=copy.deepcopy(source.payload),
            ))
        source.stale = True
        db.get(WatchRule, 1).updated_at = datetime(2026, 10, 22, 3)
        task.rule_ids = [3, 1, 2]
        db.commit()
        report = read_report(db)
        assert report["staleInfo"] == dict(
            reason="definition", changedAt="2026-10-21T02:00:00+00:00", ruleIds=[1, 2, 3],
        )
        assert sum(group["stockCount"] for group in report["overall"]) == len(report["stocks"])
        assert all(group["stale"] for group in report["overall"])
