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
from app.scheduler.worker import process_stock, validate_bars
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


def run(factory, calendar=None, worker=None, now=NOW, notifier=None):
    run_daily_watchlist(
        now=now,
        session_factory=factory,
        calendar=calendar or SimpleNamespace(is_trading_day=lambda day: True),
        worker=worker or (lambda *args: []),
        notifier=notifier if notifier is not None else Mock(),
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


@pytest.mark.parametrize("path", ["manual", "scheduled"])
@pytest.mark.parametrize("kind", [None, "unknown", "stock", "etf"])
def test_protective_stop_saved_for_both_evaluation_paths(factory, monkeypatch, path, kind):
    from dataclasses import asdict

    from sqlalchemy import event

    from app.market_scan.models import MarketInstrument
    from app.rules.evaluation import RuleEvaluationService
    from app.rules.schemas import RuleEvaluationSchema

    seed_bars(factory)
    monkeypatch.setattr(MarketDataService, "sync_daily_prices", Mock(return_value=25))
    with factory() as db:
        if kind is not None:
            db.add(MarketInstrument(ticker="2330", kind=kind, listed_on=DAY))
        db.add(WatchRule(
            id=3, name="月線出場", is_enabled=True, logic_operator="AND",
            conditions=[
                WatchRuleCondition(condition_id="volume_spike", params={}, sort_order=0),
                WatchRuleCondition(
                    condition_id="close_below_ma_days", params={}, role="exit", sort_order=1,
                ),
            ],
        ))
        db.commit()
        expected = {
            rule_id: RuleEvaluationSchema(**asdict(
                RuleEvaluationService(db).evaluate(db.get(WatchRule, rule_id), "2330")
            )).model_dump(mode="json", by_alias=True)
            for rule_id in (1, 3)
        }
    expected[3]["protectiveStop"] = {
        "close": 105.0,  # seed_bars adj_close
        "price": 104.85 if kind == "etf" else 103.5,
        "ma": 105.0, "buffer": 0.0, "tick": 0.05 if kind == "etf" else 0.5, "ticks": 3,
    }
    queries = []
    engine = factory.kw["bind"]

    def record_query(conn, cursor, statement, parameters, context, executemany):
        if "market_scan_instruments" in statement:
            queries.append(statement)

    def dependency():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = dependency
    event.listen(engine, "before_cursor_execute", record_query)
    try:
        with TestClient(app) as client:
            if path == "manual":
                response = client.post("/watchlist/1/evaluate", json={"ruleIds": [1, 3]})
                assert response.status_code == 200
                assert {row["ruleId"]: row["result"] for row in response.json()} == expected
            else:
                assert process_stock(factory, 1, "2330", [1, 3], DAY) == []
            response = client.get("/watchlist/evaluations")
            assert response.status_code == 200
            assert {row["ruleId"]: row["result"] for row in response.json()} == expected
        assert len(queries) == 1  # One kind lookup for the ticker, across both rules.
        with factory() as db:
            assert {
                row.rule_id: row.result for row in db.scalars(select(WatchlistEvaluation))
            } == expected
        assert expected[1]["protectiveStop"] is None
    finally:
        event.remove(engine, "before_cursor_execute", record_query)
        app.dependency_overrides.clear()


def seed_notification(factory):
    seed_saved(factory)
    with factory() as db:
        for saved in db.scalars(select(WatchlistEvaluation)):
            saved.result = {
                "dataDate": "2026-10-12", "exitTriggered": False,
                "protectiveStop": {
                    "close": 296, "price": 277.5, "ma": 279.3, "tick": 0.5, "ticks": 3,
                },
                "conditionResults": [{
                    "conditionId": "close_below_ma_days", "role": "exit", "isMet": False,
                }],
            }
        db.commit()


def test_daily_summary_queries_evaluations_once_and_sends_after_commit(factory):
    from sqlalchemy import event

    seed_notification(factory)
    with factory() as db:
        db.add(Stock(ticker="1303", name="南亞", market="上市"))
        db.add(HoldingsWatchlist(id=2, ticker="1303"))
        db.add(HoldingsWatchlist(id=3, ticker="9999", is_active=False))
        template = db.scalar(select(WatchlistEvaluation)).result
        for item_id in (2, 3):
            db.add(WatchlistEvaluation(
                item_id=item_id, rule_id=1, result=template, evaluated_at=utcnow(),
                data_version=0, rule_fingerprint="test",
            ))
        db.add(Stock(ticker="9999", name="不顯示", market="上市"))
        db.commit()
    queries = []
    engine = factory.kw["bind"]

    def record(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT") and "watchlist_evaluations" in statement:
            queries.append(statement)

    def sent(text):
        with factory() as db:
            assert db.get(ScheduleRun, 1).status == "partial_failure"
        assert text == (
            "觀察清單｜10/12 收盤｜2 檔\n【出場訊號】今日無\n【明日觸價價位】2 檔\n"
            "1303 南亞｜觸價 277.5｜月線 279.3｜收 296\n"
            "2330 台積電｜觸價 277.5｜月線 279.3｜收 296\n處理失敗 1 檔（見網頁）"
        )

    notifier = Mock(send_alert=Mock(side_effect=sent))
    event.listen(engine, "before_cursor_execute", record)
    try:
        run(
            factory, worker=lambda _, item, *args: ["failed"] if item == 2 else [],
            notifier=notifier,
        )
    finally:
        event.remove(engine, "before_cursor_execute", record)
    notifier.send_alert.assert_called_once()
    assert len(queries) == 1
    assert all(
        name in queries[0]
        for name in ("JOIN holdings_watchlist", "JOIN stocks", "JOIN watch_rules")
    )
    with factory() as db:
        # A swallowed assertion in send_alert must fail here.
        assert len(latest_run(db).errors) == 1


def test_daily_summary_skips_stale_evaluations(factory):
    seed_notification(factory)
    with factory() as db:
        db.add(Stock(ticker="1303", name="南亞", market="上市"))
        db.add(HoldingsWatchlist(id=2, ticker="1303"))
        template = db.scalar(select(WatchlistEvaluation)).result
        # The real worker marks a failed stock's saved result stale with data_version -1.
        db.add(WatchlistEvaluation(
            item_id=2, rule_id=1, result=template, evaluated_at=utcnow(),
            data_version=-1, rule_fingerprint="test",
        ))
        db.commit()
    notifier = Mock()
    run(factory, worker=lambda _, item, *args: ["failed"] if item == 2 else [], notifier=notifier)
    text = notifier.send_alert.call_args.args[0]
    assert "1303" not in text and "2330" in text and "處理失敗 1 檔" in text


def test_batch_exception_only_sends_one_failure_message(factory, monkeypatch):
    seed_notification(factory)
    reason = "交易資料失敗" * 40
    monkeypatch.setattr(
        "app.scheduler.daily_jobs.sync_market_price_events", Mock(side_effect=RuntimeError(reason))
    )
    notifier = Mock()
    run(factory, notifier=notifier)
    notifier.send_alert.assert_called_once_with(f"觀察清單排程失敗｜10/12｜{reason[:120]}")
    with factory() as db:
        assert latest_run(db).status == "failed"


@pytest.mark.parametrize("batch_failure", [False, True])
def test_telegram_failure_keeps_status_and_hides_url(factory, monkeypatch, caplog, batch_failure):
    seed_notification(factory)
    if batch_failure:
        monkeypatch.setattr(
            "app.scheduler.daily_jobs.sync_market_price_events",
            Mock(side_effect=RuntimeError("batch")),
        )
    notifier = Mock()
    notifier.send_alert.side_effect = RuntimeError("https://api.telegram.org/botSECRET/sendMessage")
    run(factory, notifier=notifier)
    with factory() as db:
        summary = latest_run(db)
        assert summary.status == ("failed" if batch_failure else "succeeded")
        errors = list(db.scalars(select(ScheduleError)))
        notification_errors = [e for e in errors if e.reason.startswith("Telegram")]
        assert len(notification_errors) == 1
        error = notification_errors[0]
        assert error.ticker is None
        assert error.batch_id == summary.batch_id
        assert error.reason == "Telegram 觀察清單通知失敗（RuntimeError）"
        assert "SECRET" not in str([e.reason for e in errors]) + caplog.text


def test_each_failed_page_records_error_and_continues(factory, monkeypatch):
    monkeypatch.setattr(
        "app.scheduler.daily_jobs.messages", lambda *a, **kw: ["one", "two", "three"]
    )
    notifier = Mock()
    notifier.send_alert.side_effect = [RuntimeError("secret"), None, ValueError("secret")]
    run(factory, notifier=notifier)
    assert [call.args[0] for call in notifier.send_alert.call_args_list] == ["one", "two", "three"]
    with factory() as db:
        summary = latest_run(db)
        assert summary.status == "succeeded"
        assert {e.reason for e in summary.errors} == {
            "Telegram 觀察清單通知失敗（RuntimeError）", "Telegram 觀察清單通知失敗（ValueError）",
        }


@pytest.mark.parametrize("volume", [0, 405])
@pytest.mark.parametrize("adjusted", [0, None])
@pytest.mark.parametrize("latest", [False, True])
def test_validate_bars_no_trade_days(factory, volume, adjusted, latest):
    from app.market_data.repository import MarketDataRepository

    seed_bars(factory)
    with factory() as db:
        bars = MarketDataRepository(db).get_all_bars("2330")
        no_trade = bars[-1] if latest else bars[-2]
        for key in ("open", "high", "low", "close"):
            setattr(no_trade, key, 0)
            setattr(no_trade, "adj_" + key, adjusted)
        no_trade.volume = volume
        if latest:
            with pytest.raises(ValueError, match="最新日K不是本次交易日"):
                validate_bars(bars, DAY)
        else:
            validate_bars(bars, DAY)


@pytest.mark.parametrize("prefix", ["", "adj_"])
def test_validate_bars_rejects_invalid_high_low(factory, prefix):
    from app.market_data.repository import MarketDataRepository

    seed_bars(factory)
    with factory() as db:
        bars = MarketDataRepository(db).get_all_bars("2330")
        setattr(bars[-2], prefix + "high", 80)
        with pytest.raises(ValueError, match="OHLC 高低價關係錯誤"):
            validate_bars(bars, DAY)


@pytest.mark.parametrize("volume", [0, 405])
@pytest.mark.parametrize("adjusted", [0, None])
def test_condition_loader_excludes_no_trade_days_from_ma(factory, volume, adjusted):
    from app.conditions.loader import load_condition_bars
    from app.conditions.moving_average import MaRisingCondition
    from app.market_data.repository import MarketDataRepository

    seed_bars(factory, count=26)
    with factory() as db:
        repository = MarketDataRepository(db)
        no_trade = repository.get_all_bars("2330")[-2]
        for key in ("open", "high", "low", "close"):
            setattr(no_trade, key, 0)
            setattr(no_trade, "adj_" + key, adjusted)
        no_trade.volume = volume
        db.commit()
        bars = load_condition_bars(repository, "2330")
        assert len(bars) == 25
        assert no_trade.trade_date not in [bar.trade_date for bar in bars]
        result = MaRisingCondition().evaluate(bars, {})
        assert result.data_sufficient
        assert result.indicators["ma"] == 105
        assert result.indicators["ma_prev"] == 105


def test_condition_loader_preserves_other_invalid_rows(factory):
    from app.conditions.loader import load_condition_bars
    from app.market_data.repository import MarketDataRepository

    seed_bars(factory, count=1)
    with factory() as db:
        repository = MarketDataRepository(db)
        bar = repository.get_all_bars("2330")[0]
        bar.adj_high = 80
        db.commit()
        loaded = load_condition_bars(repository, "2330")
        assert len(loaded) == 1
        assert loaded[0].high == 80


@pytest.mark.parametrize("length", [12, 2000, 2001, 5000])
def test_schedule_error_reason_is_bounded_after_save(factory, length):
    reason = "錯" * length
    with factory() as db:
        error = ScheduleError(batch_id="reason-test", ticker="2330", occurred_at=utcnow(),
                              reason=reason)
        db.add(error)
        db.commit()
        error_id = error.id
    with factory() as db:
        saved = db.get(ScheduleError, error_id)
        if length <= 2000:
            assert saved.reason == reason
        else:
            assert len(saved.reason) <= 2000
            assert saved.reason == "錯" * 1990 + "…（已截斷）"


@pytest.mark.parametrize("path", ["manual", "scheduled"])
@pytest.mark.parametrize("frequency", ["daily", "weekly"])
@pytest.mark.parametrize("no_friday", [False, True])
def test_frequency_cutoff_saved_by_both_paths(factory, monkeypatch, path, frequency, no_friday):
    from dataclasses import asdict

    from app.market_data.repository import MarketDataRepository
    from app.rules.evaluation import RuleEvaluationService
    from app.rules.schemas import RuleEvaluationSchema
    from app.watchlist.evaluation import WatchlistEvaluationService

    wednesday = date(2026, 10, 21)
    friday = date(2026, 10, 16)
    if no_friday:
        seed_saved(factory)
    seed_bars(factory, count=3 if no_friday else 35, latest=wednesday)
    monkeypatch.setattr(MarketDataService, "sync_daily_prices", Mock(return_value=35))
    with factory() as db:
        rule = db.get(WatchRule, 1)
        rule.evaluation_frequency = frequency
        rule.conditions[0].params = {"lookback": 1, "multiplier": 2}
        # Make the latest Wednesday disagree with Friday.
        data = MarketDataRepository(db).get_all_bars("2330")
        data[-1].volume = 10000
        db.commit()
        if not no_friday or frequency == "daily":
            prefix = data if frequency == "daily" else [b for b in data if b.trade_date <= friday]
            from app.conditions.types import ConditionBar

            expected = RuleEvaluationService.evaluate_bars(rule, "2330", [
                ConditionBar(b.trade_date, float(b.adj_open), float(b.adj_high),
                             float(b.adj_low), float(b.adj_close), b.volume)
                for b in prefix
            ])
            expected = RuleEvaluationSchema(**asdict(expected)).model_dump(
                mode="json", by_alias=True
            )
        else:
            monkeypatch.setattr(
                RuleEvaluationService, "evaluate",
                lambda *a, **kw: pytest.fail("No Friday must not evaluate the rule"),
            )
        if path == "manual":
            WatchlistEvaluationService(db).evaluate(db.get(HoldingsWatchlist, 1), [1])
    if path == "scheduled":
        assert process_stock(factory, 1, "2330", [1], wednesday) == []
    with factory() as db:
        saved = db.scalar(select(WatchlistEvaluation).where(WatchlistEvaluation.rule_id == 1))
        if no_friday and frequency == "weekly":
            assert saved.result["status"] == "insufficient_data"
            assert saved.result["dataDate"] is None
            assert saved.result["conditionResults"][0]["reason"] == "尚無週五判斷資料"
            assert saved.data_version == db.scalar(select(Stock)).data_version
        else:
            assert saved.result == expected
            assert saved.result["dataDate"] == (
                wednesday if frequency == "daily" else friday
            ).isoformat()
