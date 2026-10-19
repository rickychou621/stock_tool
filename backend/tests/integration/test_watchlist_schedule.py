from datetime import date, datetime, timedelta
from threading import Barrier, Lock
from types import SimpleNamespace
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import BigInteger, Integer, MetaData, create_engine, select
from sqlalchemy.orm import sessionmaker

from app.core.db import Base
from app.core.dependencies import get_db
from app.main import app
from app.market_data.models import Stock, StockPriceDaily
from app.market_data.service import MarketDataService
from app.rules.models import WatchRule, WatchRuleCondition
from app.scheduler.calendar import TwseCalendar
from app.scheduler.coordination import recover_interrupted
from app.scheduler.daily_jobs import run_daily_watchlist
from app.scheduler.models import ScheduleError, ScheduleRun, ScheduleSettings
from app.scheduler.service import latest_run, read_settings, utcnow
from app.scheduler.worker import process_stock
from app.watchlist.evaluation import fingerprint
from app.watchlist.models import HoldingsWatchlist, WatchlistEvaluation

DAY = date(2026, 10, 12)
NOW = datetime(2026, 10, 12, 18, tzinfo=ZoneInfo("Asia/Taipei"))


@pytest.fixture
def factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'schedule.db'}")
    metadata = MetaData()
    for table in Base.metadata.sorted_tables:
        table.to_metadata(metadata)
    for table in metadata.tables.values():
        for column in table.columns:
            if isinstance(column.type, BigInteger):
                column.type = Integer()
    metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        db.add(ScheduleSettings(id=1, enabled=True))
        db.add(Stock(ticker="2330", name="台積電", market="上市"))
        db.add(HoldingsWatchlist(id=1, ticker="2330"))
        db.add(
            WatchRule(
                id=1,
                name="爆量",
                is_enabled=True,
                logic_operator="AND",
                conditions=[WatchRuleCondition(condition_id="volume_spike", params={})],
            )
        )
        db.add(WatchRule(id=2, name="未選戰法", is_enabled=False, logic_operator="AND"))
        db.commit()
    yield factory
    engine.dispose()


def seed_bars(factory, *, count=25, latest=DAY, invalid=False, zero_volume=False):
    with factory() as db:
        for i in range(count):
            db.add(
                StockPriceDaily(
                    ticker="2330",
                    trade_date=latest - timedelta(days=count - i - 1),
                    open=100,
                    high=99 if invalid else 110,
                    low=90,
                    close=105,
                    adj_open=100,
                    adj_high=110,
                    adj_low=90,
                    adj_close=105,
                    volume=0 if zero_volume else 1000,
                )
            )
        db.commit()


def seed_saved(factory):
    with factory() as db:
        for rule_id in (1, 2):
            db.add(
                WatchlistEvaluation(
                    item_id=1,
                    rule_id=rule_id,
                    result={"status": "matched", "isMet": True},
                    evaluated_at=utcnow(),
                    data_version=0,
                    rule_fingerprint=fingerprint(db.get(WatchRule, rule_id)),
                )
            )
        db.commit()


def run(factory, calendar=None, worker=None, now=NOW):
    run_daily_watchlist(
        now=now,
        session_factory=factory,
        calendar=calendar or SimpleNamespace(is_trading_day=lambda day: True),
        worker=worker or (lambda *args: []),
    )


@pytest.mark.parametrize(
    "enabled,trading,now",
    [
        (False, True, NOW),
        (True, False, NOW),
        (True, True, NOW.replace(hour=19)),
        (True, True, NOW.replace(hour=17)),
        (True, True, NOW.replace(minute=1)),
    ],
)
def test_skips_without_run_or_errors(factory, enabled, trading, now):
    with factory() as db:
        db.get(ScheduleSettings, 1).enabled = enabled
        db.commit()
    worker = Mock(return_value=[])
    run(factory, SimpleNamespace(is_trading_day=lambda _: trading), worker, now)
    worker.assert_not_called()
    with factory() as db:
        assert db.get(ScheduleRun, 1) is None
        assert list(db.scalars(select(ScheduleError))) == []
        assert db.get(ScheduleSettings, 1).last_attempt_date is None


def test_daily_claim_survives_new_session_and_no_retry(factory):
    worker = Mock(return_value=["API 429：限流"])
    run(factory, worker=worker)
    run(factory, worker=worker)
    assert worker.call_count == 1
    with factory() as db:
        assert latest_run(db).status == "failed"
        assert latest_run(db).failed == 1
        assert len(list(db.scalars(select(ScheduleError)))) == 1
    run(factory, now=NOW + timedelta(days=1))
    with factory() as db:
        summary = latest_run(db)
        assert summary.status == "succeeded"
        assert summary.errors == []
        assert len(list(db.scalars(select(ScheduleError)))) == 1
        assert len(list(db.scalars(select(ScheduleRun)))) == 1


def test_three_parallel_workers_and_stock_failure_isolated(factory):
    with factory() as db:
        for i in range(2, 7):
            db.add(HoldingsWatchlist(id=i, ticker=str(i)))
        db.commit()
    lock, barrier = Lock(), Barrier(3)
    active = peak = 0
    seen = []

    def worker(session_factory, item_id, ticker, rule_ids, day):
        nonlocal active, peak
        with session_factory() as db:
            with lock:
                active += 1
                peak = max(peak, active)
                seen.append(db)
            barrier.wait(timeout=5)
            with lock:
                active -= 1
            if item_id == 2:
                raise RuntimeError("isolated failure")
        return []

    run(factory, worker=worker)
    assert peak == 3
    assert len({id(db) for db in seen}) == 6
    with factory() as db:
        summary = latest_run(db)
        assert (summary.succeeded, summary.failed, summary.status) == (5, 1, "partial_failure")
        assert summary.errors[0].ticker == "2"


@pytest.mark.parametrize("case", ["insufficient", "invalid", "stale", "api_error"])
def test_failure_retains_valid_result_and_marks_stale(factory, monkeypatch, case):
    seed_saved(factory)
    seed_bars(
        factory,
        count=2 if case == "insufficient" else 25,
        latest=DAY - timedelta(days=1) if case == "stale" else DAY,
        invalid=case == "invalid",
    )
    sync = Mock(
        side_effect=RuntimeError("FinMind 429") if case == "api_error" else None, return_value=25
    )
    monkeypatch.setattr(MarketDataService, "sync_daily_prices", sync)
    failures = process_stock(factory, 1, "2330", [1], DAY)
    assert failures
    assert sync.call_count == 1
    with factory() as db:
        rows = list(db.scalars(select(WatchlistEvaluation).order_by(WatchlistEvaluation.rule_id)))
        assert rows[0].result == {"status": "matched", "isMet": True}
        assert rows[0].data_version == -1
        assert rows[1].data_version == 0
        assert rows[1].result == {"status": "matched", "isMet": True}


def test_no_rules_updates_one_year_and_keeps_evaluations(factory, monkeypatch):
    seed_saved(factory)
    seed_bars(factory)
    sync = Mock(return_value=25)
    monkeypatch.setattr(MarketDataService, "sync_daily_prices", sync)
    assert process_stock(factory, 1, "2330", [], DAY) == []
    sync.assert_called_once_with("2330", days=365)
    with factory() as db:
        assert all(row.result["isMet"] for row in db.scalars(select(WatchlistEvaluation)))


def test_success_uses_shared_engine_and_accepts_zero_volume(factory, monkeypatch):
    seed_bars(factory, zero_volume=True)
    monkeypatch.setattr(MarketDataService, "sync_daily_prices", Mock(return_value=25))
    assert process_stock(factory, 1, "2330", [1], DAY) == []
    with factory() as db:
        result = db.scalar(select(WatchlistEvaluation)).result
        assert result["status"] == "not_met"
        assert result["dataDate"] == DAY.isoformat()


def test_calendar_failure_records_batch_error_without_retry(factory):
    calendar = Mock()
    calendar.is_trading_day.side_effect = RuntimeError("TWSE unavailable")
    worker = Mock()
    run(factory, calendar, worker)
    run(factory, calendar, worker)
    worker.assert_not_called()
    assert calendar.is_trading_day.call_count == 1
    with factory() as db:
        assert latest_run(db).errors[0].ticker is None
        assert latest_run(db).status == "failed"


def test_settings_api_persistence_validation_and_history(factory):
    def dependency():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = dependency
    try:
        with TestClient(app) as client:
            assert client.get("/watchlist-schedule/settings").json() == {
                "enabled": True,
                "ruleIds": [1],
            }
            assert (
                client.put(
                    "/watchlist-schedule/settings", json={"enabled": False, "ruleIds": []}
                ).status_code
                == 200
            )
            assert (
                client.put(
                    "/watchlist-schedule/settings", json={"enabled": True, "ruleIds": [2]}
                ).status_code
                == 422
            )
            assert client.get("/watchlist-schedule/latest").json() is None
            assert client.get("/watchlist-schedule/errors").json() == []
        with factory() as db:
            assert read_settings(db).model_dump() == {"enabled": False, "rule_ids": []}
    finally:
        app.dependency_overrides.clear()


def test_interruption_is_reported_without_rerun(factory):
    with factory() as db:
        db.add(
            ScheduleRun(
                id=1,
                batch_id="crashed",
                trade_date=DAY,
                started_at=utcnow(),
                status="running",
                total=3,
                succeeded=1,
                failed=0,
            )
        )
        db.get(ScheduleSettings, 1).last_attempt_date = DAY
        db.commit()
    recover_interrupted(factory)
    run(factory)
    with factory() as db:
        summary = latest_run(db)
        assert summary.batch_id == "crashed"
        assert (summary.status, summary.succeeded, summary.failed) == ("failed", 1, 2)
        assert len(summary.errors) == 1


def test_twse_calendar_uses_actual_dates_including_special_closure(respx_mock):
    route = respx_mock.get("https://www.twse.com.tw/exchangeReport/FMTQIK").mock(
        return_value=httpx.Response(
            200,
            json={
                "stat": "OK",
                "data": [
                    ["115/10/08"],
                    ["115/10/12"],
                ],
            },
        )
    )
    calendar = TwseCalendar()
    assert calendar.is_trading_day(DAY)
    assert not calendar.is_trading_day(date(2026, 10, 9))
    assert not calendar.is_trading_day(date(2026, 10, 13))  # e.g. emergency closure
    assert not calendar.is_trading_day(date(2026, 10, 11))
    assert route.call_count == 3
    route.mock(return_value=httpx.Response(200, json={"stat": "bad"}))
    with pytest.raises(ValueError):
        calendar.is_trading_day(DAY)


def test_selected_rules_filters_disabled_and_inactive_watchlist(factory):
    with factory() as db:
        db.get(ScheduleSettings, 1).rule_ids = [1, 2, 999]
        db.add(HoldingsWatchlist(id=2, ticker="2317", is_active=False))
        db.commit()
    worker = Mock(return_value=[])
    run(factory, worker=worker)
    assert worker.call_count == 1
    assert worker.call_args.args[1:] == (1, "2330", [1], DAY)


def test_long_history_and_unsupported_rule_do_not_block_valid_rule(factory, monkeypatch):
    seed_bars(factory)
    with factory() as db:
        db.add(
            WatchRule(
                id=3,
                name="長週期月K",
                is_enabled=True,
                conditions=[
                    WatchRuleCondition(condition_id="macd_positive", params={"long_period": 48}),
                ],
            )
        )
        db.add(
            WatchRule(
                id=4,
                name="未實作",
                is_enabled=True,
                conditions=[
                    WatchRuleCondition(condition_id="missing_condition", params={}),
                ],
            )
        )
        db.commit()
    sync = Mock(return_value=25)
    monkeypatch.setattr(MarketDataService, "sync_daily_prices", sync)
    failures = process_stock(factory, 1, "2330", [1, 3, 4], DAY)
    assert sync.call_args.kwargs["days"] == 51 * 31
    assert any("月K資料不足" in error for error in failures)
    assert any("無法準備戰法" in error for error in failures)
    with factory() as db:
        assert db.scalar(select(WatchlistEvaluation)).rule_id == 1


def test_scheduler_registers_one_job_and_next_fire_is_not_catchup(monkeypatch):
    from app.scheduler import scheduler as module

    monkeypatch.setattr(module, "recover_interrupted", lambda _: None)
    monkeypatch.setattr(module, "run_daily_watchlist", lambda: None)
    module.start_scheduler()
    try:
        jobs = module.scheduler.get_jobs()
        assert {job.id for job in jobs} == {"daily-watchlist", "daily-market-scan"}
        jobs = [job for job in jobs if job.id == "daily-watchlist"]
        job = jobs[0]
        assert job.max_instances == 1
        assert job.misfire_grace_time == 30
        next_fire = job.trigger.get_next_fire_time(None, NOW.replace(minute=1))
        assert next_fire == NOW + timedelta(days=1)
    finally:
        module.stop_scheduler()


@pytest.fixture(autouse=True)
def isolate_market_event_http(monkeypatch):
    for method in ("price_events", "tpex_price_events"):
        monkeypatch.setattr(f"app.data_source.twse_client.TwseBatchClient.{method}", lambda *a: [])
    monkeypatch.setattr(
        "app.data_source.finmind_client.FinMindClient.get_price_events", lambda *a, **kw: []
    )


def test_schedule_many_stocks_fetches_split_once_before_workers(factory, monkeypatch):
    from app.data_source.finmind_client import FinMindClient

    split = Mock(return_value=[])
    monkeypatch.setattr(FinMindClient, "get_price_events", split)
    with factory() as db:
        for ticker in ("1", "2", "3"):
            db.add(Stock(ticker=ticker, name=ticker, market="上市"))
            db.add(HoldingsWatchlist(ticker=ticker))
        db.commit()
    calls = []

    def worker(sessions, item, ticker, rules, day):
        assert split.call_count == 1
        client = Mock(
            get_daily_price=Mock(return_value=[]), get_dividend_events=Mock(return_value=[])
        )
        with sessions() as db:
            MarketDataService(db, client).sync_daily_prices(ticker)
        client.get_price_events.assert_not_called()
        calls.append(ticker)
        return []

    run(factory, worker=worker)
    assert len(calls) == 4
    split.assert_called_once()


def test_event_failure_visible_in_schedule_errors(factory, monkeypatch):
    monkeypatch.setattr(
        "app.data_source.finmind_client.FinMindClient.get_price_events",
        Mock(side_effect=RuntimeError("secret-token")),
    )
    run(factory)
    with factory() as db:
        errors = list(db.scalars(select(ScheduleError.reason)))
        assert any("FinMind split" in e for e in errors)
        assert "secret-token" not in str(errors)
