"""API workflow tests use an isolated SQLite database and no external network."""

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import BigInteger, Integer, MetaData, create_engine, select
from sqlalchemy.orm import Session
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


def test_scan_only_returns_matches_and_never_sends_telegram(context):
    client, db, _, sent = context
    result = client.post("/screening/run")
    assert result.status_code == 200
    payload = result.json()
    assert payload["stocksScanned"] == 3
    assert [m["ticker"] for m in payload["matches"]] == ["2330"]
    assert [issue["ticker"] for issue in payload["issues"]] == ["2454"]
    assert payload["matches"][0]["isNotified"] is False
    assert sent == []
    assert len(list(db.scalars(select(AlertLog)))) == 1
    # Repeat scan still displays a match, but doesn't duplicate historical alerts.
    again = client.post("/screening/run").json()
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
    assert client.post("/screening/run").json()["matches"] == []


def test_notifications_require_explicit_action_and_skip_successful_repeats(context):
    client, _, _, sent = context
    match = client.post("/screening/run").json()["matches"][0]
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
    alert_id = client.post("/screening/run").json()["matches"][0]["id"]

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
    match = client.post("/screening/run").json()["matches"][0]
    alert = db.get(AlertLog, match["id"])
    if existing_name:
        alert.message = alert.message.replace("2330 ", "2330 台積電 ", 1)
        db.commit()
    result = client.post("/alerts/notify", json={"alertIds": [alert.id]}).json()
    assert result["sentIds"] == [alert.id]
    assert sent[0].startswith("2330 台積電 符合「爆量戰法」")
    assert sent[0].count("台積電") == 1
    assert "行情日期：" in sent[0]
    assert alert.message == sent[0]


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


def test_partial_market_update_invalidates_saved_result(context, monkeypatch):
    from app.data_source.finmind_client import FinMindClient
    from app.market_data.repository import MarketDataRepository

    client, db, rule_id, _ = context
    item = _watch_item(client)
    with monkeypatch.context() as patch:
        patch.setattr(MarketDataService, "sync_daily_prices", lambda *a, **kw: 30)
        client.post(f"/watchlist/{item['id']}/evaluate", json={"ruleIds": [rule_id]})
    assert client.get("/watchlist/evaluations").json()[0]["stale"] is False
    monkeypatch.setattr(FinMindClient, "get_daily_price", lambda *a, **kw: [])

    def fail_write(*args, **kwargs):
        raise RuntimeError("write interrupted")

    monkeypatch.setattr(MarketDataRepository, "upsert_daily_bars", fail_write)
    with pytest.raises(RuntimeError, match="write interrupted"):
        MarketDataService(db).sync_daily_prices("2330")
    db.rollback()
    assert client.get("/watchlist/evaluations").json()[0]["stale"] is True
