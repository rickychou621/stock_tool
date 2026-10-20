import copy
from datetime import date, datetime, timedelta
from threading import Barrier, Event, Lock
from types import SimpleNamespace as NS
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import BigInteger, Integer, MetaData, create_engine, delete, select
from sqlalchemy.exc import StatementError
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.core.db import Base
from app.core.dependencies import get_db
from app.data_source.finmind_client import FinMindClient
from app.main import app
from app.market_data.models import Stock, StockPriceDaily
from app.market_data.service import MarketDataService
from app.market_data.validation import valid_ohlcv
from app.market_scan.data import required_days, sync_ranges
from app.market_scan.models import (
    CandidateIndicator,
    MarketInstrument,
    ScanCandidate,
    ScanCoverage,
    ScanError,
    ScanPublication,
    ScanSettings,
    ScanTask,
)
from app.market_scan.publication import publish
from app.market_scan.rate_limit import RateLimiter
from app.market_scan.service import MarketScanManager, ScanBusy, run_daily_market_scan
from app.market_scan.universe import parse_universe, refresh_universe
from app.market_scan.worker import Outcome, evaluate_stock
from app.rules.models import WatchRule, WatchRuleCondition

DAY = date(2026, 10, 12)
NOW = datetime(2026, 10, 12, 19, tzinfo=ZoneInfo("Asia/Taipei"))
DATES = [DAY - timedelta(days=i) for i in reversed(range(40))]


def rule(rid=1, condition="bollinger_mid_up", params=None):
    return NS(
        id=rid,
        name=f"戰法{rid}",
        logic_operator="AND",
        conditions=[
            NS(
                condition_id=condition,
                params=params or {"period": 2, "slope_lookback": 1},
                sort_order=0,
            )
        ],
    )


@pytest.fixture
def factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'scan.db'}")
    meta = MetaData()
    for table in Base.metadata.sorted_tables:
        table.to_metadata(meta)
    for table in meta.tables.values():
        for column in table.columns:
            if isinstance(column.type, BigInteger):
                column.type = Integer()
    meta.create_all(engine)
    sessions = sessionmaker(bind=engine)
    with sessions() as db:
        for i in range(1, 7):
            db.add(Stock(ticker=str(i), name=f"股票{i}", market="上市"))
            db.add(
                MarketInstrument(
                    ticker=str(i), kind="stock", listed_on=date(2000, 1, 1), active=True
                )
            )
        for i in (1, 2):
            db.add(
                WatchRule(
                    id=i,
                    name=f"戰法{i}",
                    is_enabled=True,
                    conditions=[
                        WatchRuleCondition(
                            condition_id="bollinger_mid_up",
                            params={"period": 2, "slope_lookback": 1},
                        )
                    ],
                )
            )
        db.add(ScanSettings(id=1, enabled=True, rule_ids=[1, 2]))
        db.commit()
    yield sessions
    engine.dispose()


def bars(ticker="1", days=DATES, volume=0):
    return [
        StockPriceDaily(
            ticker=ticker,
            trade_date=d,
            open=10 + i,
            high=12 + i,
            low=9 + i,
            close=11 + i,
            volume=volume,
            adj_open=10 + i,
            adj_high=12 + i,
            adj_low=9 + i,
            adj_close=11 + i,
            turnover=None,
        )
        for i, d in enumerate(days)
    ]


def entry_bars(ticker="1", days=DATES):
    sample = bars(ticker, days)
    # A dip below the midline followed by a recovery is a new entry event.
    sample[-2].close = sample[-2].adj_close = sample[-2].low
    return sample


def entry_role_rule(exit_period=20):
    return NS(
        id=1,
        name="回到月線",
        logic_operator="AND",
        conditions=[
            NS(condition_id=cid, role=role, params=params, sort_order=i)
            for i, (cid, role, params) in enumerate([
                ("ma_rising", "premise", {"period": 20, "slope_lookback": 1}),
                ("price_touch_ma", "entry", {"period": 20, "tolerance": 0}),
                ("close_below_ma_days", "exit", {"period": exit_period, "days": 1}),
            ])
        ],
    )


def entry_role_bars(today_touch=True, yesterday_touch=False, rising=True):
    sample = bars()
    # The older peak allows a long-period exit to fire while the 20-day MA rises.
    closes = [100] * 15 + list(range(10, 35)) if rising else list(range(50, 10, -1))
    for bar, close in zip(sample, closes, strict=True):
        for prefix in ("", "adj_"):
            for key in ("open", "high", "low", "close"):
                setattr(bar, prefix + key, close)
    for offset, touch in ((1, today_touch), (2, yesterday_touch)):
        if touch:
            end = len(sample) - offset + 1
            ma = sum(closes[end - 20:end]) / 20
            sample[-offset].low = sample[-offset].adj_low = min(ma, closes[-offset])
    return sample


@pytest.mark.parametrize(
    "today_touch,yesterday_touch,rising,exit_period,candidates,continuing",
    [
        (True, False, True, 20, 1, 0),
        (True, True, True, 20, 0, 1),
        (False, False, True, 20, 0, 1),
        (True, False, False, 20, 0, 0),
        (True, False, True, 35, 1, 0),
    ],
)
def test_scan_entry_roles(
    today_touch, yesterday_touch, rising, exit_period, candidates, continuing
):
    sample = entry_role_bars(today_touch, yesterday_touch, rising)
    result = evaluate_stock(
        "1", "股票1", "stock", [entry_role_rule(exit_period)], sample, DATES
    )
    assert result.rules == {1: ("normal", None)}
    assert result.errors == []
    assert len(result.candidates) == candidates
    assert result.continuing == continuing
    if candidates:
        candidate = result.candidates[0]
        assert "月線上揚" in candidate["reason"]
        assert "回到月線" in candidate["reason"]
        assert "跌破月線" not in candidate["reason"]
        assert set(candidate["indicators"]) == {
            "ma_rising.ma", "ma_rising.ma_prev", "ma_rising.slope",
            "price_touch_ma.ma", "price_touch_ma.low", "price_touch_ma.close",
            "price_touch_ma.distance",
        }
        exit_ma = sum(b.close for b in sample[-exit_period:]) / exit_period
        assert (sample[-1].close < exit_ma) == (exit_period == 35)


@pytest.mark.parametrize("exit_period,previous_insufficient", [(41, False), (40, True)])
def test_scan_entry_roles_still_require_exit_history(exit_period, previous_insufficient):
    result = evaluate_stock(
        "1", "股票1", "stock", [entry_role_rule(exit_period)], entry_role_bars(), DATES
    )
    status, reason = result.rules[1]
    assert status == "insufficient_history"
    assert reason.startswith("前一個有效交易日資料不足") == previous_insufficient
    assert not result.candidates
    assert result.continuing == 0


def test_scan_entry_roles_previous_touch_without_premise_is_new_trigger():
    sample = entry_role_bars(today_touch=True, yesterday_touch=True)
    # Yesterday's MA fell from an older peak; today's MA is rising again.
    for prefix in ("", "adj_"):
        for key in ("open", "high", "low", "close"):
            setattr(sample[-22], prefix + key, 100)
    result = evaluate_stock(
        "1", "股票1", "stock", [entry_role_rule()], sample, DATES
    )
    assert result.rules == {1: ("normal", None)}
    assert len(result.candidates) == 1
    assert result.continuing == 0


def success(factory, item, rules, *args):
    return evaluate_stock(item[0], "股票" + item[0], item[1], rules, entry_bars(item[0]), DATES)


def universe(db, day):
    return [(str(i), "stock", date(2000, 1, 1)) for i in (1, 2)], None


def manager(factory, worker=success, **kwargs):
    return MarketScanManager(
        factory,
        calendar=lambda *args: DATES,
        universe=universe,
        batch_prepare=lambda *args, **kwargs: ([], []),
        worker=worker,
        notifier=Mock(),
        **kwargs,
    )


def test_universe_classification_includes_innovation_excludes_other_instruments():
    def row(section, ticker, market, cfi):
        return (
            f"<tr><td>{section}</td></tr><tr><td>{ticker}　名稱</td><td>ISIN</td>"
            f"<td>2020/01/01</td><td>{market}</td><td>產業</td><td>{cfi}</td><td></td></tr>"
        )

    html = "".join(
        [
            row("股票", "1", "上市", "ESVUFR"),
            row("股票", "2", "上櫃", "ESVUFR"),
            row("特別股", "3", "上市", "EPNRAR"),
            row("ETF", "4", "上市", "CEOGEU"),
            row("ETN", "5", "上市", "DXXXXX"),
            row("創新板", "6", "上市臺灣創新板", "ESVUFR"),
            row("上市認購(售)權證", "7", "上市", "RWSCCA"),
        ]
    )
    assert [(r["ticker"], r["kind"]) for r in parse_universe(html, DAY)] == [
        ("1", "stock"),
        ("4", "etf"),
        ("6", "stock"),
    ]
    with pytest.raises(ValueError):
        parse_universe(html[:80], DAY)


def test_universe_upsert_deactivation_completeness_and_fallback(factory):
    source = [
        dict(
            ticker=f"{1000 + i}",
            name=f"N{i}",
            kind="stock" if i < 800 else "etf",
            listed_on=date(2000, 1, 1),
            sector="半導體",
        )
        for i in range(900)
    ]
    with factory() as db:
        items, warning = refresh_universe(db, DAY, lambda d: source)
        assert len(items) == 900 and not warning
        assert not db.get(MarketInstrument, "1").active
        assert db.scalar(select(Stock).where(Stock.ticker == "1000")).name == "N0"
        assert len(refresh_universe(db, DAY, lambda d: source[:10])[0]) == 900
        failing = Mock(side_effect=RuntimeError("offline"))
        assert "沿用" in refresh_universe(db, DAY, failing)[1]
        db.execute(delete(MarketInstrument))
        db.commit()
        with pytest.raises(ValueError, match="沒有可用"):
            refresh_universe(db, DAY, failing)


@pytest.mark.parametrize(
    "change,expected",
    [
        ({"open": 0}, False),
        ({"high": 9}, False),
        ({"low": 12}, False),
        ({"close": float("nan")}, False),
        ({"volume": -1}, False),
        ({"volume": 0}, True),
    ],
)
def test_bar_validation(change, expected):
    b = dict(open=10, high=12, low=9, close=11, volume=100)
    b.update(change)
    assert valid_ohlcv(b) == expected


@pytest.mark.parametrize("lag", [0, 5, 6])
def test_valid_quote_lag_zero_volume_and_engine_metrics(lag):
    sample = entry_bars(days=DATES if lag == 0 else DATES[:-lag])
    if lag == 6:
        with pytest.raises(ValueError, match="超過 5"):
            evaluate_stock("1", "股票", "stock", [rule()], sample, DATES)
    else:
        result = evaluate_stock("1", "股票", "stock", [rule(), rule(2)], sample, DATES)
        assert len(result.candidates) == 2
        assert result.candidates[0]["older_quote"] == (lag > 0)
        assert result.candidates[0]["volume"] == 0 and result.candidates[0]["turnover"] is None
        assert result.candidates[0]["indicators"]["bollinger_mid_up.mid"] > 0
        assert "月線上揚" in result.candidates[0]["reason"]


def test_per_rule_insufficient_not_whole_stock():
    result = evaluate_stock(
        "1", "股票", "stock", [rule(), rule(2, "macd_positive")], entry_bars(), DATES
    )
    assert result.succeeded and result.insufficient and len(result.candidates) == 1
    assert result.rules[2][0] == "insufficient_history"
    assert required_days([rule(2, "macd_positive", {"long_period": 50})]) > required_days([rule()])


def test_initialization_repeated_only_missing_ranges_and_no_implicit_scan(factory, monkeypatch):
    calls = []

    def sync(self, ticker, **kwargs):
        calls.append((kwargs["start_date"], kwargs["end_date"]))
        for b in bars(
            ticker, [d for d in DATES if kwargs["start_date"] <= d <= kwargs["end_date"]]
        ):
            self._db.add(b)
        self._db.commit()
        return 1

    monkeypatch.setattr(MarketDataService, "sync_daily_prices", sync)
    with factory() as db:
        sync_ranges(db, "1", DATES[:10], Mock())
        sync_ranges(db, "1", DATES[:10], Mock())
        sync_ranges(db, "1", DATES[:12], Mock())
        assert calls == [(DATES[0], DATES[9]), (DATES[10], DATES[11])]
        assert db.get(ScanCoverage, "1")
    job = manager(factory)
    job.start([1], kind="initialize", now=NOW)
    job.close()
    with factory() as db:
        assert db.get(ScanTask, "initialize").status == "completed"
        assert db.get(ScanTask, "scan") is None and db.get(ScanPublication, 1) is None
    job.notifier.send_alert.assert_not_called()


def test_invalid_source_never_overwrites_existing_or_retries(factory, respx_mock):
    route = respx_mock.get("https://api.finmindtrade.com/api/v4/data").mock(
        return_value=httpx.Response(
            200,
            json={
                "status": 200,
                "data": [
                    dict(date=DAY.isoformat(), open=0, max=12, min=9, close=11, Trading_Volume=0)
                ],
            },
        )
    )
    # Both data calls return same mock; stub dividend parsing independently.
    client = FinMindClient(before_request=Mock())
    client.get_dividend_events = Mock(return_value=[])
    with factory() as db:
        db.add(bars(days=[DAY])[0])
        db.commit()
        with pytest.raises(ValueError, match="行情無效"):
            MarketDataService(db, client).sync_daily_prices("1", start_date=DAY, end_date=DAY)
        assert db.scalar(select(StockPriceDaily.close)) == 11
        assert route.call_count == 1 and client.before_request.call_count == 1
    route.mock(return_value=httpx.Response(200, json={"status": 402, "msg": "quota"}))
    with factory() as db:
        with pytest.raises(RuntimeError):
            MarketDataService(db, client).sync_daily_prices("1", start_date=DAY, end_date=DAY)
    assert route.call_count == 2


def test_shared_limiter_paces_all_workers():
    time = [0.0]
    seen = []
    limiter = RateLimiter(
        4, clock=lambda: time[0], sleep=lambda seconds: time.__setitem__(0, time[0] + seconds)
    )

    def request():
        limiter.acquire()
        seen.append(time[0])

    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=5) as pool:
        list(pool.map(lambda _: request(), range(10)))
    assert seen == [15 * i for i in range(1, 11)]
    with pytest.raises(ValueError):
        Settings(market_scan_workers=0)


def test_atomic_publication_per_rule_stale_unselected_removal_and_counts(factory):
    job = manager(factory)
    job.start([1, 2], now=NOW)
    job.close()
    with factory() as db:
        assert len(list(db.scalars(select(ScanCandidate)))) == 4
        old_batch = db.get(ScanPublication, 1).metadata_json["batchId"]
    entered, release = Event(), Event()

    def partial(factory, item, rules, *args):
        entered.set()
        assert release.wait(5)
        if item[0] == "2":
            return Outcome(
                "2",
                rules={1: ("insufficient_history", "不足")},
                errors=[(1, "insufficient_history", "不足")],
            )
        return Outcome("1", rules={1: ("normal", None)})  # Success no longer matches.

    job.worker = partial
    try:
        job.start([1], now=NOW)
        assert entered.wait(5)
        with factory() as db:
            assert db.get(ScanPublication, 1).metadata_json["batchId"] == old_batch
            assert len(list(db.scalars(select(ScanCandidate)))) == 4
    finally:
        release.set()
        job.close()
    with factory() as db:
        candidates = list(db.scalars(select(ScanCandidate)))
        assert len(candidates) == 2 and all(c.ticker == "2" for c in candidates)
        assert {c.status for c in candidates} == {"stale", "insufficient_history"}
        report = db.get(ScanPublication, 1).metadata_json
        assert (
            report["normalCount"] == 0 and report["succeeded"] == 1 and report["insufficient"] == 1
        )
        assert db.get(ScanSettings, 1).rule_ids == [1, 2]
    assert "掃描完成" in job.notifier.send_alert.call_args.args[0]
    with factory() as db:
        assert db.get(ScanTask, "scan").status == "completed"


def test_publish_rollback_and_restart_keep_previous(factory):
    job = manager(factory)
    job.start([1], now=NOW)
    job.close()
    with factory() as db:
        old = copy.deepcopy(db.get(ScanPublication, 1).metadata_json)
        db.get(ScanTask, "scan").status = "running"
        db.commit()
        bad = success(factory, ("1", "stock", DAY), [rule()])
        bad.candidates[0]["indicators"] = {"bad": object()}
        with pytest.raises(StatementError):
            publish(db, old["batchId"], [bad], old)
        db.rollback()
        assert db.get(ScanPublication, 1).metadata_json == old
        assert len(list(db.scalars(select(ScanCandidate)))) == 2
    job.recover()
    with factory() as db:
        assert db.get(ScanTask, "scan").status == "interrupted"
        assert db.get(ScanPublication, 1).metadata_json == old


def test_five_workers_sessions_and_mutual_exclusion_but_backtest_independent(factory):
    barrier, entered, release, lock = Barrier(5), Event(), Event(), Lock()
    active = peak = 0
    seen = []

    def worker(sessions, item, rules, *args):
        nonlocal active, peak
        with sessions() as db:
            with lock:
                active += 1
                peak = max(peak, active)
                seen.append(db)
            entered.set()
            assert release.wait(5)
            if item[0] != "6":
                barrier.wait(5)
            with lock:
                active -= 1
        return success(sessions, item, rules)

    job = manager(factory, worker)
    job.universe = lambda *args: ([(str(i), "stock", DAY) for i in range(1, 7)], None)
    try:
        job.start([1], now=NOW)
        assert entered.wait(5)
        for kind in ("scan", "initialize"):
            with pytest.raises(ScanBusy):
                manager(factory).start([1], kind=kind, now=NOW)
        from app.backtest.coordination import acquire

        lease = acquire(factory)
        assert lease is not None
        lease.close()
        job.recover()
        with factory() as db:
            assert db.get(ScanTask, "scan").status == "running"
    finally:
        release.set()
        job.close()
    assert peak == 5 and len({id(s) for s in seen}) == 6


@pytest.mark.parametrize(
    "hour,enabled,trading,expected",
    [
        (18, True, True, False),
        (20, True, True, False),
        (19, False, True, False),
        (19, True, False, False),
        (19, True, True, True),
    ],
)
def test_schedule_timezone_trading_closures_disabled_no_catchup(
    factory, hour, enabled, trading, expected
):
    with factory() as db:
        db.get(ScanSettings, 1).enabled = enabled
        db.commit()
    job = manager(factory)
    calendar = Mock()
    calendar.is_trading_day.return_value = trading
    run_daily_market_scan(NOW.replace(hour=hour).astimezone(ZoneInfo("UTC")), calendar, job)
    job.close()
    with factory() as db:
        assert (db.get(ScanTask, "scan") is not None) == expected
    if expected:
        job.start = Mock()
        run_daily_market_scan(NOW, calendar, job)
        job.start.assert_not_called()


def test_empty_auto_rules_skipped_keeps_candidates_manual_rejected(factory):
    job = manager(factory)
    job.start([1], now=NOW)
    job.close()
    with factory() as db:
        db.get(ScanSettings, 1).rule_ids = []
        db.commit()
    with pytest.raises(ValueError):
        job.start([], now=NOW)
    job.start(source="automatic", now=NOW)
    with factory() as db:
        assert db.get(ScanTask, "scan").status == "skipped"
        assert "未選擇戰法" in db.get(ScanTask, "scan").warnings
        assert len(list(db.scalars(select(ScanCandidate)))) == 2


@pytest.mark.parametrize(
    "mode,status,label",
    [
        ("success", "completed", "掃描完成"),
        ("insufficient", "failed", "掃描失敗"),
        ("mixed", "completed", "掃描完成"),
        ("partial", "partial_completed", "部分失敗，明細見下一則"),
        ("failed", "failed", "掃描失敗"),
    ],
)
def test_task_statuses_notifications_failure_isolation_and_holiday_manual(
    factory, mode, status, label
):
    def worker(factory, item, rules, *args):
        if mode == "failed" or (mode == "partial" and item[0] == "2"):
            raise RuntimeError("unavailable")
        if mode == "insufficient" or (mode == "mixed" and item[0] == "2"):
            # Insufficient history is informational unless nothing was evaluated at all.
            return Outcome(item[0], rules={1: ("insufficient_history", "不足")})
        return success(factory, item, rules)

    job = manager(factory, worker)
    job.notifier.send_alert.side_effect = RuntimeError("secret URL must not leak")
    job.start([1], now=NOW.replace(day=11))
    job.close()  # Sunday is permitted manually.
    with factory() as db:
        task = db.get(ScanTask, "scan")
        assert task.status == status and task.processed == 2
        assert any("Telegram" in w for w in task.warnings)
        assert not any("secret" in w for w in task.warnings)
    assert any(label in call.args[0] for call in job.notifier.send_alert.call_args_list)


def test_api_pagination_filters_actual_turnover_metrics_and_bounds(factory, monkeypatch):
    job = manager(factory)
    monkeypatch.setattr("app.market_scan.router.manager", job)
    job.start([1, 2], now=NOW)
    job.close()
    with factory() as db:
        base = db.scalar(select(ScanCandidate))
        for i in range(60):
            db.add(
                ScanCandidate(
                    ticker=f"X{i:02}",
                    stock_name="測試ETF",
                    kind="etf",
                    rule_id=1,
                    rule_name="戰法1",
                    batch_id=base.batch_id,
                    status="normal",
                    reason="符合",
                    indicators={},
                    close=i + 1,
                    price_date=DAY,
                    volume=i,
                    turnover=1000 + i,
                    scanned_at=NOW.replace(tzinfo=None),
                    older_quote=False,
                )
            )
        db.flush()
        for c in db.scalars(select(ScanCandidate)):
            if c.ticker.startswith("X"):
                db.add(
                    CandidateIndicator(candidate_id=c.id, name="test.value", value=float(c.close))
                )
        db.commit()

    def dependency():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = dependency
    try:
        with TestClient(app) as client:
            result = client.get("/market-scan/candidates").json()
            assert result["total"] == 64 and len(result["items"]) == 50
            assert len(client.get("/market-scan/candidates?page=2").json()["items"]) == 14
            result = client.get(
                "/market-scan/candidates?kind=etf&search=測試&minVolume=59&sort=turnover&direction=desc"
            ).json()
            assert result["total"] == 1 and result["items"][0]["ticker"] == "X59"
            assert (
                client.get(
                    "/market-scan/candidates?indicator=test.value&indicatorMin=60&sort=indicator"
                ).json()["total"]
                == 1
            )
            assert client.get("/market-scan/candidates?minTurnover=0").json()["total"] == 60
            assert (
                client.get(
                    "/market-scan/candidates?priceDate=2026-10-12&minPrice=59&maxPrice=60"
                ).json()["total"]
                == 2
            )
            for query in (
                "sort=sql",
                "page=10001",
                "pageSize=500",
                "sort=indicator",
                "minPrice=nan",
            ):
                assert client.get("/market-scan/candidates?" + query).status_code == 422
            report = client.get("/market-scan/summary").json()
            assert report["succeeded"] == 2 and report["normalCount"] == 4
            assert client.post("/market-scan/run", json={"ruleIds": []}).status_code == 422
            assert (
                client.put(
                    "/market-scan/settings", json={"enabled": False, "ruleIds": []}
                ).status_code
                == 200
            )
            assert client.get("/market-scan/errors").json()["total"] == 0
    finally:
        app.dependency_overrides.clear()


def test_existing_complete_prices_only_supplement_dividend_coverage(factory, monkeypatch):
    with factory() as db:
        db.add_all(bars())
        db.commit()
        sync = Mock(return_value=0)
        monkeypatch.setattr(MarketDataService, "sync_daily_prices", sync)
        sync_ranges(db, "1", DATES, Mock())
        assert sync.call_count == 1 and sync.call_args.kwargs["fetch_prices"] is False
        sync_ranges(db, "1", DATES, Mock())
        assert sync.call_count == 1


def test_worker_only_reads_database_without_external_sync(factory, monkeypatch):
    from app.market_scan.data import prepare

    with factory() as db:
        sync = Mock(return_value=0)
        monkeypatch.setattr(MarketDataService, "sync_daily_prices", sync)
        prepare(db, "1", date(2000, 1, 1), "scan", [rule(2, "macd_positive")], DATES, Mock())
        prepare(db, "1", date(2000, 1, 1), "scan", [rule(2, "macd_positive")], DATES, Mock())
        sync.assert_not_called()


def test_current_month_without_trades_still_allows_holiday_manual_baseline(
    factory, respx_mock, monkeypatch
):
    from app.market_scan.service import load_market_trading_dates

    monkeypatch.setattr("app.backtest.data.taipei_today", lambda: date(2026, 10, 1))
    respx_mock.get(
        "https://www.twse.com.tw/exchangeReport/FMTQIK",
        params={"response": "json", "date": "20260901"},
    ).mock(return_value=httpx.Response(200, json={"stat": "OK", "data": [["115/09/30"]]}))
    respx_mock.get(
        "https://www.twse.com.tw/exchangeReport/FMTQIK",
        params={"response": "json", "date": "20261001"},
    ).mock(return_value=httpx.Response(200, json={"stat": "很抱歉，沒有符合條件的資料!"}))
    assert load_market_trading_dates(factory, date(2026, 9, 1), date(2026, 10, 1)) == [
        date(2026, 9, 30)
    ]


def test_schedule_calendar_failure_is_persisted_and_not_retried(factory):
    job = manager(factory)
    calendar = Mock()
    calendar.is_trading_day.side_effect = RuntimeError("offline")
    run_daily_market_scan(NOW, calendar, job)
    run_daily_market_scan(NOW, calendar, job)
    assert calendar.is_trading_day.call_count == 1
    with factory() as db:
        task = db.get(ScanTask, "scan")
        assert task.status == "failed" and task.source == "automatic"
        assert db.get(ScanPublication, 1) is None


def test_disabled_rule_in_saved_settings_is_skipped_without_poisoning_other_rules(factory):
    job = manager(factory)
    with factory() as db:
        db.get(WatchRule, 2).is_enabled = False
        db.commit()
    job.start(source="automatic", now=NOW)
    job.close()
    with factory() as db:
        assert db.get(ScanTask, "scan").rules == [{"id": 1, "name": "戰法1"}]


def test_api_conflict_settings_independent_and_refresh_never_syncs(factory, monkeypatch):
    release, entered = Event(), Event()

    def worker(*args):
        entered.set()
        assert release.wait(5)
        return success(*args)

    job = manager(factory, worker)
    monkeypatch.setattr("app.market_scan.router.manager", job)

    def dependency():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = dependency
    try:
        with TestClient(app) as client:
            assert client.post("/market-scan/run", json={"ruleIds": [1]}).status_code == 202
            assert entered.wait(5)
            assert client.post("/market-scan/initialize", json={"ruleIds": [1]}).status_code == 409
            assert client.post("/market-scan/run", json={"ruleIds": [1]}).status_code == 409
            assert client.get("/market-scan/settings").json()["ruleIds"] == [1, 2]
            assert (
                client.put(
                    "/market-scan/settings", json={"enabled": False, "ruleIds": [2]}
                ).status_code
                == 200
            )
            # Disabling future schedules doesn't cancel this job.
            assert client.get("/market-scan/tasks").json()["scan"]["status"] == "running"
            release.set()
            job.close()
            job.universe = Mock(side_effect=AssertionError("GET must not refresh universe"))
            sync = Mock(side_effect=AssertionError("GET must not sync FinMind"))
            monkeypatch.setattr(MarketDataService, "sync_daily_prices", sync)
            for endpoint in ("tasks", "settings", "summary", "candidates", "errors", "indicators"):
                assert client.get("/market-scan/" + endpoint).status_code == 200
            sync.assert_not_called()
            job.universe.assert_not_called()
    finally:
        release.set()
        job.close()
        app.dependency_overrides.clear()


def test_one_rule_failure_preserves_only_that_old_pair_and_next_auto_replaces_manual(factory):
    job = manager(factory)
    job.start([1, 2], now=NOW)
    job.close()

    def partial(factory, item, rules, *args):
        good = success(factory, item, [rules[0]])
        good.rules[2] = ("insufficient_history", "不足")
        return good

    job.worker = partial
    job.start([1, 2], now=NOW)
    job.close()
    with factory() as db:
        rows = list(db.scalars(select(ScanCandidate)))
        assert {r.status for r in rows if r.rule_id == 1} == {"normal"}
        assert {r.status for r in rows if r.rule_id == 2} == {"insufficient_history"}
        db.get(ScanSettings, 1).rule_ids = [2]
        db.commit()
    job.worker = success
    job.start(source="automatic", now=NOW)
    job.close()
    with factory() as db:
        rows = list(db.scalars(select(ScanCandidate)))
        assert len(rows) == 2 and all(r.rule_id == 2 and r.status == "normal" for r in rows)
        assert db.get(ScanPublication, 1).metadata_json["source"] == "automatic"


@pytest.mark.parametrize("all_fail,expected", [(False, "partial_completed"), (True, "failed")])
def test_initialization_partial_and_failure_no_scan_or_notification(factory, all_fail, expected):
    def worker(factory, item, rules, *args):
        if all_fail or item[0] == "2":
            raise RuntimeError("來源失敗")
        return success(factory, item, rules)

    job = manager(factory, worker)
    job.start([1], kind="initialize", now=NOW)
    job.close()
    with factory() as db:
        task = db.get(ScanTask, "initialize")
        assert task.status == expected and task.processed == 2
        assert db.get(ScanTask, "scan") is None
        assert db.get(ScanPublication, 1) is None
    job.notifier.send_alert.assert_not_called()


def test_dividend_record_date_overlap_filters_actual_ex_dates(factory, monkeypatch):
    from app.market_data.repository import MarketDataRepository

    client = Mock()
    client.get_daily_price.return_value = []
    actual = dict(
        ex_dividend_date=DAY,
        cash_dividend=1,
        stock_dividend_ratio=0,
        cash_capital_increase_ratio=0,
        cash_capital_increase_price=0,
    )
    client.get_dividend_events.return_value = [
        actual,
        dict(actual, ex_dividend_date=DAY + timedelta(days=3)),
    ]
    saved = []
    monkeypatch.setattr(
        MarketDataRepository,
        "upsert_dividend_events",
        lambda self, ticker, events: saved.extend(events),
    )
    with factory() as db:
        MarketDataService(db, client).sync_daily_prices("1", start_date=DAY, end_date=DAY)
    client.get_dividend_events.assert_called_once_with(
        "1", start_date=DAY - timedelta(days=31), end_date=DAY + timedelta(days=31)
    )
    assert saved == [actual]


@pytest.mark.parametrize("adjusted", [None, 0])
def test_no_trade_history_is_skipped_but_invalid_history_is_stale(adjusted):
    from app.market_data.validation import is_no_trade

    rows = entry_bars()
    zero = rows[10]
    for key in ("open", "high", "low", "close"):
        setattr(zero, key, 0)
        setattr(zero, "adj_" + key, adjusted)
    assert is_no_trade(zero) and not valid_ohlcv(zero)
    expected = evaluate_stock("1", "股票1", "stock", [rule()], rows[:10] + rows[11:], DATES)
    actual = evaluate_stock("1", "股票1", "stock", [rule()], rows, DATES)
    assert actual.succeeded and not actual.failed
    assert actual.rules == expected.rules
    assert actual.continuing == expected.continuing
    assert actual.candidates[0]["indicators"] == expected.candidates[0]["indicators"]
    # Odd-lot or block-trade volume on a zero-price day is still a no-trade day.
    zero.volume = 405
    assert is_no_trade(zero)
    assert evaluate_stock("1", "股票1", "stock", [rule()], rows, DATES).rules == expected.rules
    rows[11].high = rows[11].low - 1
    assert not is_no_trade(rows[11])
    assert evaluate_stock("1", "股票1", "stock", [rule()], rows, DATES).failed


def notification_fixture(factory, status="completed", count=0):
    with factory() as db:
        db.add(
            ScanTask(
                kind="scan",
                batch_id="notify",
                source="manual",
                status=status,
                started_at=datetime(2026, 10, 20),
                finished_at=datetime(2026, 10, 20, 1, 26),
                baseline=date(2026, 10, 19),
                rules=[],
                warnings=[],
            )
        )
        db.add(ScanPublication(id=1, metadata_json={"batchId": "notify", "continuing": 407}))
        for i in range(count):
            db.add(
                ScanCandidate(
                    ticker=f"{i:04}",
                    stock_name="測試股票😀",
                    kind="stock",
                    rule_id=2,
                    rule_name="戰法二：布林上軌區間",
                    batch_id="notify",
                    status="normal",
                    reason="突破布林上軌",
                    indicators={},
                    close=1045,
                    turnover=31_250_000_000 - i,
                    price_date=date(2026, 10, 17),
                    volume=1,
                    scanned_at=datetime(2026, 10, 20),
                    older_quote=True,
                )
            )
        db.commit()
    return manager(factory, settings=Settings(market_scan_notify_min_turnover=0))


def add_notification_error(
    db, ticker, status="failed", reason="行情落後 134 個交易日，超過 5 日", **kwargs
):
    db.add(
        ScanError(
            kind="scan", batch_id="notify", ticker=ticker, status=status, reason=reason, **kwargs
        )
    )


def test_notification_group_sort_formats_marks_and_current_normal_only(factory):
    job = notification_fixture(factory, count=6)
    with factory() as db:
        rows = list(db.scalars(select(ScanCandidate).order_by(ScanCandidate.ticker)))
        rows[0].turnover = None
        rows[1].turnover = 9_820_000_000
        rows[1].close = 1380.50
        rows[1].reason = ""
        rows[1].indicators = {"訊號": "觸及布林上軌"}
        rows[2].rule_id, rows[2].rule_name = 1, "戰法一"
        rows[3].batch_id = "old"
        rows[4].status = "stale"
        rows[5].status = "insufficient_history"
        db.commit()
    job.notify("notify")
    job.notifier.send_alert.assert_called_once()
    text = job.notifier.send_alert.call_args.args[0]
    assert text.startswith("全市場掃描完成｜基準日 2026-10-19｜完成 09:26（台北）")
    assert "進場事件 3 筆（趨勢中未觸發 407 筆）" in text
    assert text.index("【戰法一】1 筆") < text.index("【戰法二：布林上軌區間】2 筆")
    assert text.index("0001 測試股票") < text.index("0000 測試股票")
    assert "收 1045｜成交 312.5 億｜突破上軌｜較舊行情 10/17" in text
    assert "收 1380.5｜成交 98.2 億｜觸及上軌" in text
    assert "成交 —" in text
    assert all(ticker not in text for ticker in ("0003", "0004", "0005"))


def test_notification_empty_and_no_failure_details_for_informational_errors(factory):
    job = notification_fixture(factory)
    with factory() as db:
        add_notification_error(db, "1", "warning")
        add_notification_error(db, "2", "insufficient_history")
        for rid in (1, 2):
            add_notification_error(db, "1589", "suspended", rule_id=rid)
        db.commit()
    job.notify("notify")
    job.notifier.send_alert.assert_called_once()
    text = job.notifier.send_alert.call_args.args[0]
    assert "今日沒有進場事件" in text
    assert "進場事件 0 筆（趨勢中未觸發 407 筆；停止交易 1 檔）" in text


def test_notification_pages_preserve_every_line_and_utf16_limit(factory):
    from app.alerts.notification import MESSAGE_LIMIT, _text_size

    job = notification_fixture(factory, count=180)
    job.notify("notify")
    texts = [call.args[0] for call in job.notifier.send_alert.call_args_list]
    assert len(texts) >= 3
    for i, text in enumerate(texts, 1):
        assert _text_size(text) <= MESSAGE_LIMIT
        if i > 1:
            assert text.startswith(f"全市場掃描結果（續 {i}/{len(texts)}）\n")
    entries = [line for text in texts for line in text.splitlines() if "測試股票" in line]
    assert len(entries) == 180
    for i, line in enumerate(entries):
        assert line == f"{i:04} 測試股票😀｜收 1045｜成交 312.5 億｜突破上軌｜較舊行情 10/17"


@pytest.mark.parametrize(
    "status,expected", [("partial_completed", 2), ("failed", 1), ("completed", 2)]
)
def test_notification_failure_deduplication_truncation_and_status(factory, status, expected):
    from app.alerts.notification import _shorten

    job = notification_fixture(factory, status, count=1)
    with factory() as db:
        for i in range(23):
            add_notification_error(db, f"E{i:02}", "stale", "錯😀" * 100, rule_id=1)
            add_notification_error(db, f"E{i:02}", reason="第二戰法不應出現", rule_id=2)
        for rid in (1, 2):
            add_notification_error(db, "short", "insufficient_history", rule_id=rid)
        add_notification_error(db, "warn", "warning", reason="不列警告")
        db.add(
            ScanError(
                kind="initialize",
                batch_id="notify",
                ticker="wrong",
                status="failed",
                reason="不列初始化",
            )
        )
        db.add(
            ScanError(
                kind="scan", batch_id="old", ticker="old", status="failed", reason="不列舊批次"
            )
        )
        db.commit()
    job.notify("notify")
    assert job.notifier.send_alert.call_count == expected
    text = job.notifier.send_alert.call_args.args[0]
    assert text.startswith("全市場掃描失敗｜" if status == "failed" else "處理失敗 23 檔｜")
    assert f"E00 {_shorten('錯😀' * 100, 120)}" in text
    assert "E19 " in text and "E20 " not in text
    assert "其餘 3 檔見網頁錯誤列表" in text
    assert "資料不足 1 檔（未逐一列出，見網頁錯誤列表）" in text
    assert all(s not in text for s in ("第二戰法", "不列"))
    if status == "partial_completed":
        assert "部分失敗，明細見下一則" in job.notifier.send_alert.call_args_list[0].args[0]


@pytest.mark.parametrize("both_fail", [False, True])
def test_notification_send_failure_still_attempts_details_and_records_each_warning(
    factory, both_fail
):
    job = notification_fixture(factory, "partial_completed")
    with factory() as db:
        add_notification_error(db, "1589")
        db.commit()
    secret = RuntimeError("https://secret-token.invalid")
    job.notifier.send_alert.side_effect = [secret, secret if both_fail else None]
    job.notify("notify")
    assert job.notifier.send_alert.call_count == 2
    assert job.notifier.send_alert.call_args.args[0].startswith("處理失敗 1 檔")
    with factory() as db:
        warnings = db.get(ScanTask, "scan").warnings
        assert len(warnings) == (2 if both_fail else 1)
        assert all("Telegram" in warning and "RuntimeError" in warning for warning in warnings)
        assert "secret" not in str(warnings)


def test_notification_turnover_units_and_reason_without_exception_name():
    from app.market_scan.notification import _reason, _turnover

    assert _turnover(None) == "—"
    assert _turnover(312_500_000) == "3.1 億"
    assert _turnover(35_120_000) == "3,512 萬"
    assert _turnover(4_000) == "0 萬"
    reason = "行情落後 134 個交易日，超過 5 日"
    assert _reason(f"ValueError: {reason}") == reason
    assert _reason("2025-07-30 歷史行情無效") == "2025-07-30 歷史行情無效"


@pytest.mark.parametrize("lag", [21, 39])
def test_long_quote_lag_is_suspended_without_candidates(lag):
    result = evaluate_stock("1", "股票1", "stock", [rule(), rule(2)], bars()[:-lag], DATES)
    reason = (
        f"停止交易或長期無行情：落後 {lag} 個交易日"
        f"（最後行情 {DATES[-lag - 1]}）"
    )
    assert result.suspended
    assert not result.succeeded and not result.failed and not result.insufficient
    assert result.rules == {1: ("suspended", reason), 2: ("suspended", reason)}
    assert result.errors == [(None, "suspended", reason)]
    assert result.candidates == [] and result.continuing == 0


@pytest.mark.parametrize(
    "lag,all_suspended,status,failed",
    [
        (21, False, "completed", 0),
        (6, False, "partial_completed", 1),
        (20, False, "partial_completed", 1),
        (21, True, "failed", 0),
    ],
)
def test_quote_lag_task_status_and_notification(factory, lag, all_suspended, status, failed):
    def worker(factory, item, rules, *args):
        if item[0] == "1" and not all_suspended:
            return success(factory, item, rules)
        return evaluate_stock(
            item[0], "股票" + item[0], item[1], rules, bars(item[0])[:-lag], DATES
        )

    job = manager(factory, worker)
    job.start(now=NOW)
    job.close()
    with factory() as db:
        task = db.get(ScanTask, "scan")
        assert task.status == status and task.failed == failed
        assert task.processed == 2 and task.insufficient == 0
        assert task.succeeded == (0 if all_suspended else 1)
        errors = list(db.scalars(select(ScanError)))
        assert len(errors) == (2 if all_suspended else 1)
        assert {e.status for e in errors} == {"suspended" if lag > 20 else "stale"}
        assert not list(db.scalars(select(ScanCandidate).where(ScanCandidate.ticker == "2")))
    texts = [call.args[0] for call in job.notifier.send_alert.call_args_list]
    if status == "completed":
        assert len(texts) == 1
        assert "停止交易 1 檔" in texts[0] and "部分失敗" not in texts[0]
    elif status == "partial_completed":
        assert len(texts) == 2 and "部分失敗" in texts[0]
    else:
        assert len(texts) == 1 and texts[0].startswith("全市場掃描失敗")


@pytest.mark.parametrize("threshold,label", [(10_000_000, "1,000 萬"),
                                             (50_000_000, "5,000 萬"),
                                             (100_000_000, "1 億")])
def test_notification_turnover_threshold_filters_display_only(factory, threshold, label):
    job = notification_fixture(factory, count=4)
    job.settings.market_scan_notify_min_turnover = threshold
    with factory() as db:
        rows = list(db.scalars(select(ScanCandidate).order_by(ScanCandidate.ticker)))
        for row, turnover in zip(
            rows, [None, threshold - 1, threshold, threshold + 1], strict=True
        ):
            row.turnover = turnover
        add_notification_error(db, "halted", "suspended")
        db.commit()
    job.notify("notify")
    text = job.notifier.send_alert.call_args.args[0]
    assert (f"進場事件 4 筆（成交金額 ≥ {label} 2 筆；"
            "趨勢中未觸發 407 筆；停止交易 1 檔）") in text
    assert "0000 測試股票" not in text and "0001 測試股票" not in text
    assert "0002 測試股票" in text and "0003 測試股票" in text
    assert text.endswith(f"另有 2 筆成交金額未達 {label}，未列出（見網頁）")
    with factory() as db:
        assert len(list(db.scalars(select(ScanCandidate)))) == 4


def test_notification_turnover_all_excluded(factory):
    job = notification_fixture(factory, count=2)
    job.settings.market_scan_notify_min_turnover = 10_000_000
    with factory() as db:
        rows = list(db.scalars(select(ScanCandidate).order_by(ScanCandidate.ticker)))
        rows[0].turnover, rows[1].turnover = None, 9_999_999
        db.commit()
    job.notify("notify")
    text = job.notifier.send_alert.call_args.args[0]
    assert "今日沒有成交金額 ≥ 1,000 萬的進場事件" in text
    assert "另有 2 筆成交金額未達 1,000 萬，未列出（見網頁）" in text
    assert "測試股票" not in text


def test_notification_zero_threshold_preserves_exact_output(factory):
    from app.market_scan.notification import messages

    job = notification_fixture(factory, count=1)
    with factory() as db:
        candidate = db.scalar(select(ScanCandidate))
        candidate.turnover = None
        db.commit()
        task = db.get(ScanTask, "scan")
        expected = (
            "全市場掃描完成｜基準日 2026-10-19｜完成 09:26（台北）\n"
            "進場事件 1 筆（趨勢中未觸發 407 筆）\n\n"
            "【戰法二：布林上軌區間】1 筆\n"
            "0000 測試股票😀｜收 1045｜成交 —｜突破上軌｜較舊行情 10/17"
        )
        assert messages(task, [candidate], [], 407) == [expected]
        assert messages(task, [candidate], [], 407, min_turnover=0) == [expected]
    job.notify("notify")
    assert job.notifier.send_alert.call_args.args[0] == expected
