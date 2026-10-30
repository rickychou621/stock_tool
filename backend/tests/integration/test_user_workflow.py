"""API workflow tests use an isolated SQLite database and no external network."""

from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import BigInteger, Integer, MetaData, create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.alerts.models import AlertLog
from app.core.db import Base
from app.core.dependencies import get_db
from app.data_source.notifier import TelegramNotifier
from app.main import app
from app.market_data.models import Stock, StockPriceDaily
from app.market_data.service import MarketDataService
from app.rules.models import WatchRule, WatchRuleCondition
from app.rules.preparation import history_days
from app.screening import router as screening_router
from app.screening.jobs import ScanJobManager


@pytest.fixture
def context(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    # SQLite autoincrement requires INTEGER exactly; production models remain unchanged.
    metadata = MetaData()
    for table in Base.metadata.sorted_tables:
        table.to_metadata(metadata)
    for table in metadata.tables.values():
        for column in table.columns:
            if isinstance(column.type, BigInteger):
                column.type = Integer()
    metadata.create_all(engine)
    scan_manager = ScanJobManager(session_factory=sessionmaker(bind=engine))
    monkeypatch.setattr(screening_router, "manager", scan_manager)
    monkeypatch.setattr("app.main.screening_manager", scan_manager)
    with Session(engine) as db:
        db.add_all([Stock(ticker=t, name=t, market="上市") for t in ("2330", "2317", "2454")])
        for ticker, count in (("2330", 30), ("2317", 30), ("2454", 1)):
            for i in range(count):
                db.add(
                    StockPriceDaily(
                        ticker=ticker,
                        trade_date=date.today() - timedelta(days=count - i),
                        open=100,
                        high=100,
                        low=100,
                        close=100,
                        adj_close=100,
                        volume=5000 if ticker == "2330" and i == count - 1 else 1000,
                    )
                )
        rule = WatchRule(
            name="爆量戰法",
            logic_operator="AND",
            is_enabled=True,
            conditions=[WatchRuleCondition(condition_id="volume_spike", params={})],
        )
        db.add(rule)
        db.commit()
        sent = []
        monkeypatch.setattr(
            TelegramNotifier, "send_alert", lambda self, message: sent.append(message)
        )
        app.dependency_overrides[get_db] = lambda: db
        with TestClient(app) as client:
            yield client, db, rule.id, sent
        app.dependency_overrides.clear()
    engine.dispose()


def run_scan(client):
    response = client.post("/screening/run")
    assert response.status_code == 202
    screening_router.manager.close()
    latest = client.get("/screening/run/latest").json()
    assert latest["jobId"] == response.json()["jobId"]
    assert latest["status"] == "done", latest["error"]
    return latest["summary"]


def test_scan_only_returns_matches_and_never_sends_telegram(context):
    client, db, rule_id, sent = context
    started = datetime.now(UTC)
    payload = run_scan(client)
    latest_date = db.scalar(select(func.max(StockPriceDaily.trade_date)))
    assert payload["baselineDate"] == latest_date.isoformat()
    assert payload["matches"][0]["ruleId"] == rule_id
    assert client.get("/screening/run/latest").json()["latestMarketDate"] == latest_date.isoformat()
    assert payload["finishedAt"] is not None
    assert started <= datetime.fromisoformat(payload["finishedAt"]) <= datetime.now(UTC)
    assert payload["stocksScanned"] == 3
    assert payload["excluded"] == 0
    assert payload["matches"][0]["name"] == "2330"
    assert payload["matches"][0]["reason"]
    assert client.get("/alerts").json()[0]["name"] == "2330"
    assert [m["ticker"] for m in payload["matches"]] == ["2330"]
    assert [issue["ticker"] for issue in payload["issues"]] == ["2454"]
    assert payload["matches"][0]["isNotified"] is False
    assert sent == []
    assert len(list(db.scalars(select(AlertLog)))) == 1
    # Repeat scan still displays a match, but doesn't duplicate historical alerts.
    again = run_scan(client)
    assert again["newAlerts"] == 0
    assert len(again["matches"]) == 1
    # Today's historical match must not appear as a current match after data changes.
    bar = db.scalar(
        select(StockPriceDaily)
        .where(StockPriceDaily.ticker == "2330")
        .order_by(StockPriceDaily.trade_date.desc())
    )
    bar.volume = 1000
    db.commit()
    assert run_scan(client)["matches"] == []


def test_notifications_require_explicit_action_and_skip_successful_repeats(context):
    client, _, _, sent = context
    match = run_scan(client)["matches"][0]
    alert_id = match["id"]
    result = client.post("/alerts/notify", json={"alertIds": [alert_id, alert_id]}).json()
    assert result == {"sentIds": [alert_id], "skippedIds": [], "failedIds": []}
    assert len(sent) == 1
    again = client.post("/alerts/notify", json={"alertIds": [alert_id]}).json()
    assert again["skippedIds"] == [alert_id]
    assert len(sent) == 1
    assert client.post("/alerts/notify", json={"alertIds": [9999]}).json()["failedIds"] == [9999]
    assert len(sent) == 1


def test_failed_notification_can_be_retried(context, monkeypatch):
    client, _, _, sent = context
    alert_id = run_scan(client)["matches"][0]["id"]

    def fail(self, message):
        raise RuntimeError("unavailable")

    monkeypatch.setattr(TelegramNotifier, "send_alert", fail)
    assert client.post("/alerts/notify", json={"alertIds": [alert_id]}).json()["failedIds"] == [
        alert_id
    ]
    monkeypatch.setattr(TelegramNotifier, "send_alert", lambda self, message: sent.append(message))
    assert client.post("/alerts/notify", json={"alertIds": [alert_id]}).json()["sentIds"] == [
        alert_id
    ]
    assert len(sent) == 1


def test_evaluation_distinguishes_missing_data_from_unmet_condition(context):
    client, _, rule_id, sent = context
    enough = client.get(f"/rules/{rule_id}/evaluate?ticker=2317").json()
    missing = client.get(f"/rules/{rule_id}/evaluate?ticker=2454").json()
    assert enough["status"] == "not_met"
    assert missing["status"] == "insufficient_data"
    assert missing["conditionResults"][0]["dataSufficient"] is False
    assert enough["dataDate"] is not None
    assert sent == []


def test_adding_watchlist_is_idempotent_and_does_not_sync_or_evaluate(context, monkeypatch):
    client, _, _, sent = context

    def forbidden(*args, **kwargs):
        pytest.fail("Adding a stock must not sync market data")

    monkeypatch.setattr(MarketDataService, "sync_daily_prices", forbidden)
    first = client.post("/watchlist", json={"ticker": " 2330 "})
    second = client.post("/watchlist", json={"ticker": "2330"})
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    assert len(client.get("/watchlist").json()) == 1
    assert sent == []


def test_prepare_updates_history_but_does_not_notify(context, monkeypatch):
    client, _, rule_id, sent = context
    calls = []

    def sync(self, ticker, days):
        calls.append((ticker, days))
        return 30

    monkeypatch.setattr(MarketDataService, "sync_daily_prices", sync)
    response = client.post(f"/rules/{rule_id}/prepare?ticker=2330")
    assert response.status_code == 200
    assert response.json()["rowsSynced"] == 30
    assert calls[0][0] == "2330"
    assert calls[0][1] >= 180
    assert sent == []


@pytest.mark.parametrize("failure", ["empty", "network"])
def test_prepare_failure_is_visible_instead_of_silently_using_old_prices(
    context, monkeypatch, failure
):
    client, _, rule_id, _ = context

    def sync(self, ticker, days):
        if failure == "network":
            raise RuntimeError("network failed")
        return 0

    monkeypatch.setattr(MarketDataService, "sync_daily_prices", sync)
    response = client.post(f"/rules/{rule_id}/prepare?ticker=2330")
    assert response.status_code == (422 if failure == "empty" else 502)
    assert "未評估" in response.json()["detail"]


def test_monthly_rule_requests_enough_calendar_history():
    rule = WatchRule(
        conditions=[WatchRuleCondition(condition_id="macd_histogram_rising", params={})]
    )
    assert 27 * 31 <= history_days(rule) <= 1000


@pytest.mark.parametrize("existing_name", [False, True])
def test_notification_includes_stock_name_once(context, existing_name):
    client, db, _, sent = context
    stock = db.scalar(select(Stock).where(Stock.ticker == "2330"))
    stock.name = "台積電"
    db.commit()
    match = run_scan(client)["matches"][0]
    alert = db.get(AlertLog, match["id"])
    if existing_name:
        alert.message = alert.message.replace("2330 ", "2330 台積電 ", 1)
        db.commit()
    result = client.post("/alerts/notify", json={"alertIds": [alert.id]}).json()
    assert result["sentIds"] == [alert.id]
    assert "2330 台積電 符合「爆量戰法」" in sent[0]
    assert sent[0].count("台積電") == 1
    assert "行情日期：" in sent[0]
    assert alert.message.startswith("2330 台積電 符合「爆量戰法」")
    assert "符合戰法摘要" not in alert.message


def _watch_item(client):
    return client.post("/watchlist", json={"ticker": "2330", "notes": "原始筆記"}).json()


def test_multi_rule_evaluation_syncs_once_and_persists_across_requests(context, monkeypatch):
    client, db, rule_id, sent = context
    other = WatchRule(
        name="長週期",
        logic_operator="AND",
        is_enabled=True,
        conditions=[WatchRuleCondition(condition_id="macd_positive", params={})],
    )
    db.add(other)
    db.commit()
    calls = []
    monkeypatch.setattr(
        MarketDataService,
        "sync_daily_prices",
        lambda self, ticker, days: calls.append((ticker, days)) or 30,
    )
    item = _watch_item(client)
    response = client.post(
        f"/watchlist/{item['id']}/evaluate", json={"ruleIds": [rule_id, other.id, rule_id]}
    )
    assert response.status_code == 200
    results = response.json()
    assert len(calls) == 1
    assert calls[0] == ("2330", max(history_days(db.get(WatchRule, rule_id)), history_days(other)))
    assert len(results) == 2
    assert results[0]["result"]["status"] == "matched"
    assert results[1]["result"]["status"] == "insufficient_data"
    db.expire_all()
    restored = client.get("/watchlist/evaluations").json()
    assert restored == results
    assert all(not r["stale"] for r in restored)
    assert all(r["evaluatedAt"].endswith("Z") for r in restored)
    assert sent == []


def test_saved_evaluation_becomes_stale_after_price_or_rule_change(context, monkeypatch):
    client, db, rule_id, _ = context
    monkeypatch.setattr(MarketDataService, "sync_daily_prices", lambda *a, **kw: 30)
    item = _watch_item(client)
    url = f"/watchlist/{item['id']}/evaluate"
    client.post(url, json={"ruleIds": [rule_id]})
    stock = db.scalar(select(Stock).where(Stock.ticker == "2330"))
    stock.data_version += 1
    db.commit()
    assert client.get("/watchlist/evaluations").json()[0]["stale"] is True
    client.post(url, json={"ruleIds": [rule_id]})
    assert client.get("/watchlist/evaluations").json()[0]["stale"] is False
    rule = db.get(WatchRule, rule_id)
    rule.conditions[0].params = {"lookback": 10}
    db.commit()
    assert client.get("/watchlist/evaluations").json()[0]["stale"] is True


def test_edit_holding_roundtrips_notes_and_stock_sector(context):
    client, _, _, _ = context
    item = _watch_item(client)
    values = {
        "entryPrice": 123.45,
        "entryDate": "2026-09-29",
        "notes": "保留\n觀察原因",
        "sector": "半導體",
    }
    response = client.patch(f"/watchlist/{item['id']}", json=values)
    assert response.status_code == 200
    restored = client.get("/watchlist").json()[0]
    for key, value in values.items():
        assert restored[key] == value
    assert client.get("/stocks/2330").json()["sector"] == "半導體"
    assert (
        client.patch(f"/watchlist/{item['id']}", json={**values, "entryPrice": -1}).status_code
        == 422
    )
    assert client.get("/watchlist").json()[0]["entryPrice"] == 123.45
    assert (
        client.patch(
            f"/watchlist/{item['id']}",
            json={"notes": "清除進場資料", "entryPrice": None, "entryDate": None},
        ).status_code
        == 200
    )
    assert client.get("/watchlist").json()[0]["entryPrice"] is None


def test_failed_sync_saves_failure_without_evaluating_old_data(context, monkeypatch):
    client, _, rule_id, sent = context

    def fail(*args, **kwargs):
        raise RuntimeError("source unavailable")

    monkeypatch.setattr(MarketDataService, "sync_daily_prices", fail)
    item = _watch_item(client)
    results = client.post(f"/watchlist/{item['id']}/evaluate", json={"ruleIds": [rule_id]}).json()
    assert results[0]["result"]["status"] == "error"
    assert results[0]["result"]["isMet"] is False
    assert "行情更新失敗" in results[0]["result"]["conditionResults"][0]["reason"]
    assert client.get("/watchlist/evaluations").json() == results
    assert sent == []


def test_removed_holding_and_missing_rule_do_not_sync(context, monkeypatch):
    client, _, rule_id, _ = context
    calls = []
    monkeypatch.setattr(MarketDataService, "sync_daily_prices", lambda *a, **kw: calls.append(1))
    item = _watch_item(client)
    assert (
        client.post(f"/watchlist/{item['id']}/evaluate", json={"ruleIds": [99999]}).status_code
        == 422
    )
    client.delete(f"/watchlist/{item['id']}")
    assert (
        client.post(f"/watchlist/{item['id']}/evaluate", json={"ruleIds": [rule_id]}).status_code
        == 404
    )
    assert client.patch(f"/watchlist/{item['id']}", json={"notes": "x"}).status_code == 404
    assert calls == []


def test_failed_atomic_market_update_preserves_saved_result(context, monkeypatch):
    from app.data_source.finmind_client import FinMindClient
    from app.market_data.repository import MarketDataRepository

    client, db, rule_id, _ = context
    item = _watch_item(client)
    with monkeypatch.context() as patch:
        patch.setattr(MarketDataService, "sync_daily_prices", lambda *a, **kw: 30)
        client.post(f"/watchlist/{item['id']}/evaluate", json={"ruleIds": [rule_id]})
    assert client.get("/watchlist/evaluations").json()[0]["stale"] is False
    monkeypatch.setattr(FinMindClient, "get_daily_price", lambda *a, **kw: [])

    monkeypatch.setattr(FinMindClient, "get_dividend_events", lambda *a, **kw: [])

    def fail_write(*args, **kwargs):
        raise RuntimeError("write interrupted")

    monkeypatch.setattr(MarketDataRepository, "upsert_daily_bars", fail_write)
    with pytest.raises(RuntimeError, match="write interrupted"):
        MarketDataService(db).sync_daily_prices("2330")
    db.rollback()
    assert client.get("/watchlist/evaluations").json()[0]["stale"] is False


@pytest.mark.parametrize("count, sizes", [(50, [50]), (51, [50, 1]), (120, [50, 50, 20])])
def test_notification_batches_at_most_fifty_entries(context, monkeypatch, count, sizes):
    client, db, rule_id, sent = context
    monkeypatch.setattr("app.alerts.notification.sleep", lambda _: None)
    alerts = [
        AlertLog(
            rule_id=rule_id,
            ticker="2330",
            message=f"2330 符合「戰法{i}」\n行情日期：2026-10-13，參考價：100\n完整判斷理由",
        )
        for i in range(count)
    ]
    db.add_all(alerts)
    db.commit()
    ids = [alert.id for alert in alerts]
    result = client.post("/alerts/notify", json={"alertIds": ids + [ids[0]]}).json()
    assert result == {"sentIds": ids, "skippedIds": [], "failedIds": []}
    assert [len(message.splitlines()) - 1 for message in sent] == sizes
    assert all("完整判斷理由" not in message for message in sent)
    assert all("完整判斷理由" in alert.message for alert in alerts)
    again = client.post("/alerts/notify", json={"alertIds": ids + [99999]}).json()
    assert again == {"sentIds": [], "skippedIds": ids, "failedIds": [99999]}
    assert len(sent) == len(sizes)


def test_batch_failure_only_retries_failed_message(context, monkeypatch):
    client, db, rule_id, sent = context
    monkeypatch.setattr("app.alerts.notification.sleep", lambda _: None)
    alerts = [
        AlertLog(rule_id=rule_id, ticker="2330", message=f"2330 符合「戰法{i}」")
        for i in range(101)
    ]
    db.add_all(alerts)
    db.commit()
    ids = [alert.id for alert in alerts]
    attempts = []

    def send(self, message):
        attempts.append(message)
        if len(attempts) == 2:
            raise RuntimeError("unavailable")
        sent.append(message)

    monkeypatch.setattr(TelegramNotifier, "send_alert", send)
    result = client.post("/alerts/notify", json={"alertIds": ids}).json()
    assert result == {"sentIds": ids[:50] + ids[100:], "skippedIds": [], "failedIds": ids[50:100]}
    again = client.post("/alerts/notify", json={"alertIds": ids}).json()
    assert again == {"sentIds": ids[50:100], "skippedIds": ids[:50] + ids[100:], "failedIds": []}
    assert len(sent) == 3


def test_long_unicode_digest_splits_without_losing_alerts(context, monkeypatch):
    client, db, rule_id, sent = context
    monkeypatch.setattr("app.alerts.notification.sleep", lambda _: None)
    db.scalar(select(Stock).where(Stock.ticker == "2330")).name = "台積電"
    alerts = [
        AlertLog(
            rule_id=rule_id,
            ticker="2330",
            message=(
                f"2330 符合「{'🌕' * 100}{i}」\n"
                "行情日期：2026-10-13，參考價：100\n"
                "當日最高價觸及布林上軌100.00（壓力參考）"
            ),
        )
        for i in range(50)
    ]
    db.add_all(alerts)
    db.commit()
    ids = [alert.id for alert in alerts]
    result = client.post("/alerts/notify", json={"alertIds": ids}).json()
    assert result["sentIds"] == ids
    assert result["failedIds"] == []
    assert len(sent) > 1
    assert sum(len(message.splitlines()) - 1 for message in sent) == 50
    assert all(len(message.encode("utf-16-le")) // 2 <= 4096 for message in sent)
    assert sum(message.count("台積電") for message in sent) == 50
    assert sum(message.count("觸及上軌") for message in sent) == 50


def test_scan_progress_counts_stocks_after_all_rules_and_excludes_etfs(context, monkeypatch):
    from app.core.config import get_settings
    from app.market_scan.models import MarketInstrument
    from app.screening import scan_service

    _, db, _, _ = context
    monkeypatch.setattr(get_settings(), "screening_excluded_etf_categories", "bond")
    db.add(MarketInstrument(ticker="2454", kind="etf", etf_category="bond",
                            listed_on=date.today()))
    db.add(WatchRule(name="第二戰法", logic_operator="AND", is_enabled=True,
                     conditions=[WatchRuleCondition(condition_id="volume_spike", params={})]))
    db.commit()
    evaluated = []
    updates = []
    evaluate = scan_service.evaluate_with_state

    def record(*args, **kwargs):
        evaluated.append(args[2])
        return evaluate(*args, **kwargs)

    def progress(done, total):
        assert len(evaluated) == done * 2
        updates.append((done, total))

    monkeypatch.setattr(scan_service, "evaluate_with_state", record)
    summary = scan_service.ScreeningScanService(db).run_scan(progress=progress)
    assert updates == [(0, 2), (1, 2), (2, 2)]
    assert updates[-1] == (summary.stocks_scanned, summary.stocks_scanned)
    assert evaluated[0] == evaluated[1]
    assert evaluated[2] == evaluated[3]
    assert "2454" not in evaluated


def test_chart_date_range_and_legacy_limit(context):
    client, db, *_ = context
    start = date.today() - timedelta(days=20)
    end = date.today() - timedelta(days=10)
    response = client.get(f"/chart/2330?start={start}&end={end}&limit=1")
    assert response.status_code == 200
    bars = response.json()
    assert len(bars) == 11
    assert bars[0]["date"] == start.isoformat()
    assert bars[-1]["date"] == end.isoformat()
    assert [b["date"] for b in bars] == sorted(b["date"] for b in bars)
    assert len(client.get(f"/chart/2330?start={start}").json()) == 20
    latest = client.get("/chart/2330?limit=2").json()
    assert len(latest) == 2
    assert latest[-1]["date"] == (date.today() - timedelta(days=1)).isoformat()
    assert client.get("/chart/2330?limit=501").status_code == 422
    assert client.get("/chart/2330?start=invalid").status_code == 422
    assert client.get(f"/chart/2330?start={end}&end={start}").json() == []


def test_chart_date_range_caps_at_1000_and_uses_adjusted_prices(context):
    client, db, *_ = context
    start = date(2000, 1, 1)
    for i in range(1005):
        db.add(StockPriceDaily(
            ticker="2330", trade_date=start + timedelta(days=i),
            open=100, high=120, low=90, close=110, volume=1000,
            adj_open=10, adj_high=12, adj_low=9, adj_close=11,
        ))
    db.commit()
    bars = client.get(f"/chart/2330?start={start}").json()
    assert len(bars) == 1000
    assert bars[0] == dict(date="2000-01-01", open=10, high=12, low=9, close=11, volume=1000)
    assert bars[-1]["date"] == (start + timedelta(days=999)).isoformat()


def test_screening_stale_entry_has_no_alert(context):
    client, db, rule_id, sent = context
    # Use a real ENTRY first, then advance another stock's daily quote.
    current = run_scan(client)
    assert current["matches"][0]["state"] == "ENTRY"
    alert = db.scalar(select(AlertLog))
    original_message = alert.message
    db.query(AlertLog).delete()
    latest = db.scalar(select(StockPriceDaily).where(
        StockPriceDaily.ticker == "2330"
    ).order_by(StockPriceDaily.trade_date.desc()))
    old_day = latest.trade_date
    new_day = old_day + timedelta(days=1)
    db.add(StockPriceDaily(ticker="2454", trade_date=new_day,
                          open=100, high=100, low=100, close=100, volume=1000))
    db.commit()
    stale = run_scan(client)
    match = next(m for m in stale["matches"] if m["ticker"] == "2330")
    assert match["state"] == "STALE"
    assert match["id"] is None
    assert match["reason"] == f"行情過期：最後行情 {old_day}，最近交易日 {new_day}"
    assert stale["newAlerts"] == 0
    assert list(db.scalars(select(AlertLog))) == []
    assert sent == []
    # A pre-existing alert must not be updated by a stale evaluation.
    db.add(AlertLog(rule_id=rule_id, ticker="2330", message=original_message,
                    is_notified=False, state="ENTRY"))
    db.commit()
    assert run_scan(client)["matches"][0]["id"] is None
    db.expire_all()
    assert db.scalar(select(AlertLog)).message == original_message


def test_etf_exclusion_settings_and_futures_screening(context, monkeypatch):
    from app.core.config import get_settings
    from app.market_scan.models import MarketInstrument, ScanSettings

    client, db, _, _ = context
    monkeypatch.setattr(get_settings(), "screening_excluded_etf_categories", "futures")
    db.add(Stock(ticker="00682U", name="期元大美元指數", market="上市"))
    db.flush()
    db.add(MarketInstrument(ticker="00682U", kind="etf", etf_category="futures",
                            listed_on=date(2000, 1, 1)))
    for bar in list(db.scalars(select(StockPriceDaily).where(StockPriceDaily.ticker == "2330"))):
        db.add(StockPriceDaily(ticker="00682U", trade_date=bar.trade_date,
                              open=bar.open, high=bar.high, low=bar.low,
                              close=bar.close, volume=bar.volume))
    db.add(ScanSettings(id=1, excluded_etf_categories=None))
    db.commit()
    assert client.get("/settings").json()["excludedEtfCategories"] == ["futures"]
    result = run_scan(client)
    assert result["excludedCategories"] == ["futures"]
    assert "00682U" not in [m["ticker"] for m in result["matches"]]
    for invalid in (["equity"], ["unknown"], ["futures", "stock"]):
        response = client.put("/settings/etf-exclusion", json={"categories": invalid})
        assert response.status_code == 422
    assert client.put("/settings/etf-exclusion", json={"categories": []}).status_code == 200
    assert client.get("/settings").json()["excludedEtfCategories"] == []
    assert "00682U" in [m["ticker"] for m in run_scan(client)["matches"]]
    assert client.put("/settings/etf-exclusion", json={"categories": ["bond"]}).status_code == 200
    assert client.get("/settings").json()["excludedEtfCategories"] == ["bond"]


def test_large_stop_distance_setting_defaults_and_updates(context):
    client, _, _, _ = context
    assert client.get("/settings").json()["largeStopDistancePct"] == 0.07
    for invalid in (0, 1, -0.1):
        response = client.put("/settings/stop-distance", json={"largeStopDistancePct": invalid})
        assert response.status_code == 422
    response = client.put("/settings/stop-distance", json={"largeStopDistancePct": 0.08})
    assert response.status_code == 200
    assert response.json() == {"largeStopDistancePct": 0.08}
    assert client.get("/settings").json()["largeStopDistancePct"] == 0.08


@pytest.mark.parametrize("state", ["ENTRY", "HOLD", "NEAR_EXIT", "EXIT"])
def test_screening_all_match_states_use_daily_quote_date(context, monkeypatch, state):
    from types import SimpleNamespace

    from app.screening import scan_service

    _, db, rule_id, _ = context
    latest = db.scalar(select(StockPriceDaily.trade_date).order_by(
        StockPriceDaily.trade_date.desc()))
    old = latest - timedelta(days=11)
    monkeypatch.setattr(scan_service, "evaluate_with_state", lambda *args, **kwargs: (
        SimpleNamespace(status="ok", data_date=old, condition_results=[]),
        SimpleNamespace(state=state, reason="符合", ma_distance_pct=None,
                        ma_slope_pct=None, stop_distance_pct=None, large_stop_distance=False),
    ))
    summary = scan_service.ScreeningScanService(db).run_scan()
    assert len(summary.matches) == 3
    assert all(m.state == "STALE" and m.id is None for m in summary.matches)
    assert all(str(old) in m.reason and str(latest) in m.reason for m in summary.matches)
    assert summary.new_alerts == 0



def test_screening_weekly_rule_uses_last_friday_as_fresh(context, monkeypatch):
    client, db, rule_id, sent = context
    from types import SimpleNamespace

    from app.rules.state import RuleState
    from app.screening import scan_service

    latest = db.scalar(select(func.max(StockPriceDaily.trade_date)))
    friday = latest - timedelta(days=(latest.weekday() - 4) % 7)
    db.query(StockPriceDaily).filter(StockPriceDaily.trade_date > friday).delete()
    db.get(WatchRule, rule_id).evaluation_frequency = "weekly"
    # Newer non-Friday quotes exist, but weekly rules are still judged on that Friday.
    for offset in (3, 4):
        db.add(StockPriceDaily(ticker="2454", trade_date=friday + timedelta(days=offset),
                              open=100, high=100, low=100, close=100, volume=1000))
    db.commit()
    for data_date, expected in ((friday, "ENTRY"), (friday - timedelta(days=7), "STALE")):
        monkeypatch.setattr(scan_service, "evaluate_with_state", lambda *a, d=data_date, **k: (
            SimpleNamespace(status="matched", data_date=d, condition_results=[]),
            RuleState("ENTRY", "ok", None, None, None),
        ))
        db.query(AlertLog).delete()
        db.commit()
        states = {m["state"] for m in run_scan(client)["matches"] if m["ticker"] == "2330"}
        assert states == {expected}


def test_latest_scan_reads_current_market_date_without_rescanning(context):
    client, db, _, _ = context
    summary = run_scan(client)
    db.add(StockPriceDaily(
        ticker="2330", trade_date=date.today(), open=100, high=100, low=100,
        close=100, adj_close=100, volume=1000,
    ))
    db.commit()
    latest = client.get("/screening/run/latest").json()
    assert latest["latestMarketDate"] == date.today().isoformat()
    assert latest["summary"] == summary
