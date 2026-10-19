"""Price-event ingestion, adjustment and cached backtest regression coverage."""

# ruff: noqa: F811
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from unittest.mock import Mock

import pytest
from sqlalchemy import select
from test_market_scan import factory, rule  # noqa: F401

from app.backtest.costs_benchmark import load_benchmark
from app.data_source.finmind_client import FINMIND_BASE_URL, FinMindClient
from app.data_source.twse_client import (
    BASE,
    TwseBatchClient,
    parse_price_events,
    parse_tpex_price_events,
)
from app.market_data.models import Stock, StockPriceDaily, StockPriceEvent, StockPriceEventSync
from app.market_data.price_adjustment import DividendEvent, PriceBar, PriceEvent, apply_adjustment
from app.market_data.price_event_sync import sync_market_price_events
from app.market_data.service import MarketDataService
from app.market_scan.batch_data import synchronize
from app.market_scan.models import DividendCoverage

DAY = date(2025, 6, 18)
BEFORE = DAY - timedelta(days=8)


def split(ticker="1", reference="47.16"):
    return dict(
        ticker=ticker,
        event_date=DAY,
        event_type="split",
        before_close=Decimal("188.65"),
        reference_price=Decimal(reference),
        source="finmind_split",
    )


def bar(day, price):
    return PriceBar(day, price, price, price, price)


@pytest.mark.parametrize("before,after", [(188.65, 47.16), (10, 100), (40.15, 41.73)])
def test_price_factor_and_event_day_unchanged(before, after):
    rows = [bar(BEFORE, before), bar(DAY, after)]
    result = apply_adjustment(rows, [], [PriceEvent(DAY, before, after)])
    for key in ("open", "high", "low", "close"):
        assert result[BEFORE][key] == pytest.approx(after)
        assert result[DAY][key] == after


def test_same_day_dividend_and_price_event_and_legacy_compatibility():
    rows = [bar(BEFORE, 188.65), bar(DAY, 47.16)]
    dividends = [DividendEvent(DAY, cash_dividend=2)]
    legacy = apply_adjustment(rows, dividends)
    assert apply_adjustment(rows, dividends, []) == legacy
    adjusted = apply_adjustment(rows, dividends, [PriceEvent(DAY, 188.65, 47.16)])
    assert adjusted[BEFORE]["close"] == pytest.approx(legacy[BEFORE]["close"] * 47.16 / 188.65)
    assert adjusted[DAY] == legacy[DAY]


def payload():
    return dict(
        stat="OK",
        fields=["除權參考價", "股票代號", "恢復買賣日期", "恢復買賣參考價", "停止買賣前收盤價格"],
        data=[["--", "2371", "114/06/23", "41.73", "40.15"]],
    )


def test_twtauu_roc_date_and_unused_missing_field():
    (row,) = parse_price_events(payload(), DAY, date(2025, 6, 30))
    assert row["event_date"] == date(2025, 6, 23)
    assert row["before_close"] == Decimal("40.15")
    assert row["reference_price"] == Decimal("41.73")
    broken = payload()
    broken["data"][0][3] = "--"
    with pytest.raises(InvalidOperation):
        parse_price_events(broken, DAY, date(2025, 6, 30))
    with pytest.raises(ValueError):
        parse_price_events({"stat": "error"}, DAY, DAY)


def seed(db, ticker="1"):
    service = MarketDataService(db)
    for day, value in [(BEFORE, 188.65), (DAY, 47.16)]:
        service.import_market_day(
            day,
            [
                dict(
                    ticker=ticker,
                    trade_date=day,
                    open=value,
                    high=value,
                    low=value,
                    close=value,
                    volume=100,
                )
            ],
        )
    db.commit()


def test_new_event_correction_idempotence_and_history_fill(factory):
    with factory() as db:
        seed(db)
        service = MarketDataService(db)
        service.import_price_events("1", [split()])
        db.commit()
        old = db.scalar(select(StockPriceDaily).where(StockPriceDaily.trade_date == BEFORE))
        assert old.adj_close == Decimal("47.16")
        version = db.scalar(select(Stock.data_version).where(Stock.ticker == "1"))
        service.import_price_events("1", [split()])
        db.commit()
        assert db.scalar(select(Stock.data_version).where(Stock.ticker == "1")) == version
        service.import_price_events("1", [split(reference="48")])
        db.commit()
        assert old.adj_close == Decimal("48")
        assert len(list(db.scalars(select(StockPriceEvent)))) == 1
        day = BEFORE + timedelta(days=1)
        service.import_market_day(
            day,
            [
                dict(
                    ticker="1",
                    trade_date=day,
                    open=188.65,
                    high=188.65,
                    low=188.65,
                    close=188.65,
                    volume=100,
                )
            ],
        )
        db.commit()
        assert db.scalar(
            select(StockPriceDaily.adj_close).where(StockPriceDaily.trade_date == day)
        ) == Decimal("48")


def batch(factory, mode, client=None):
    return synchronize(
        factory,
        [("1", "stock", date(2000, 1, 1))],
        [rule()],
        "initialize",
        [BEFORE, DAY],
        Mock(),
        Mock(),
        client=client,
        mode=mode,
    )


def test_price_only_all_market_once_no_quotes_or_dividends(factory, respx_mock, monkeypatch):
    monkeypatch.setattr("app.data_source.twse_client.shared_limiter", lambda: Mock())
    route = respx_mock.get(FINMIND_BASE_URL).respond(
        200,
        json=dict(
            status=200,
            data=[
                dict(
                    date=DAY.isoformat(),
                    stock_id="1",
                    type="分割",
                    before_price=188.65,
                    after_price=47.16,
                )
            ],
        ),
    )
    twse = respx_mock.get(BASE + "TWTAUU").respond(
        200, json={"stat": "很抱歉，沒有符合條件的資料!"}
    )
    respx_mock.get("https://www.tpex.org.tw/www/zh-tw/bulletin/revivt").respond(
        200, json=tpex_payload([])
    )
    with factory() as db:
        seed(db)
    warnings, errors = batch(factory, "price_events", TwseBatchClient())
    assert not errors
    assert not any("失敗" in w for w in warnings)
    assert route.call_count == 1
    assert twse.call_count == 1
    assert "data_id" not in route.calls[0].request.url.params
    assert route.calls[0].request.url.params["dataset"] == "TaiwanStockSplitPrice"
    with factory() as db:
        assert db.scalar(select(StockPriceEvent)).event_type == "split"
        assert db.get(DividendCoverage, "1") is None
        assert db.scalar(
            select(StockPriceDaily.adj_close).where(StockPriceDaily.trade_date == BEFORE)
        ) == Decimal("47.16")


@pytest.mark.parametrize("failed", ["split", "capital", "tpex"])
def test_source_failure_blocks_dividend_coverage(factory, monkeypatch, failed):
    fm = Mock(return_value=[])
    client = Mock(
        events=Mock(return_value=[]),
        price_events=Mock(return_value=[]),
        tpex_price_events=Mock(return_value=[]),
    )
    if failed == "split":
        fm.side_effect = RuntimeError("unavailable")
    elif failed == "tpex":
        client.tpex_price_events.side_effect = RuntimeError("unavailable")
    else:
        client.price_events.side_effect = RuntimeError("unavailable")
    monkeypatch.setattr(FinMindClient, "get_price_events", fm)
    warnings, _ = batch(factory, "dividends", client)
    with factory() as db:
        assert db.get(DividendCoverage, "1") is None
    assert fm.call_count == client.tpex_price_events.call_count == 1
    assert client.price_events.call_count == 1
    assert any("還原資料未完整" in w for w in warnings)
    client.daily.assert_not_called()


def test_cached_0050_benchmark_reads_stored_split_without_network(factory, monkeypatch):
    with factory() as db:
        db.add(Stock(ticker="0050", name="ETF", market="上市"))
        db.commit()
        seed(db, "0050")
        MarketDataService(db).import_price_events("0050", [split("0050")])
        db.commit()
    fetch = Mock(side_effect=AssertionError("no per-stock event requests"))
    monkeypatch.setattr(FinMindClient, "get_price_events", fetch)
    result = load_benchmark(factory, BEFORE, DAY, [BEFORE, DAY])
    assert result[BEFORE.isoformat()]["close"] == pytest.approx(47.16)
    fetch.assert_not_called()


@pytest.mark.parametrize("validated", [True, False])
def test_sync_daily_prices_never_fetches_price_events(factory, validated):
    client = Mock(get_daily_price=Mock(return_value=[]), get_dividend_events=Mock(return_value=[]))
    with factory() as db:
        seed(db)
        kwargs = dict(start_date=BEFORE, end_date=DAY) if validated else {}
        MarketDataService(db, client).sync_daily_prices("1", **kwargs)
    client.get_price_events.assert_not_called()


@pytest.mark.parametrize("ticker,expected", [("1", [True, False]), ("0050", [True, True])])
def test_event_changes_invalidate_saved_results(factory, ticker, expected):
    from datetime import datetime

    from app.backtest.models import BacktestResult

    with factory() as db:
        if ticker == "0050":
            db.add(Stock(ticker=ticker, name="ETF", market="上市"))
        for t in ("1", "2"):
            db.add(
                BacktestResult(
                    ticker=t,
                    stock_name=t,
                    rule_id=1,
                    rule_name="rule",
                    batch_id="old",
                    calculated_at=datetime.now(),
                    summary={},
                    payload={},
                )
            )
        db.commit()
        MarketDataService(db).import_price_events(ticker, [split(ticker)])
        db.commit()
        assert (
            list(db.scalars(select(BacktestResult.stale).order_by(BacktestResult.ticker)))
            == expected
        )


def tpex_payload(data=None):
    return dict(
        stat="ok",
        tables=[
            dict(
                fields=[
                    "股票代號",
                    "減資恢復買賣開始日參考價格",
                    "恢復買賣日期",
                    "最後交易日之收盤價格",
                ],
                data=[["6248", "6.92", "1020116", "4.21"]] if data is None else data,
            )
        ],
    )


def test_tpex_fields_and_compact_roc_date():
    rows = parse_tpex_price_events(tpex_payload(), date(2011, 1, 1), DAY)
    assert rows[0]["event_date"] == date(2013, 1, 16)
    assert rows[0]["reference_price"] == Decimal("6.92")
    assert rows[0]["before_close"] == Decimal("4.21")
    with pytest.raises(ValueError):
        parse_tpex_price_events(dict(stat="error"), BEFORE, DAY)
    with pytest.raises(ValueError):
        parse_tpex_price_events(dict(stat="ok", tables=[]), BEFORE, DAY)


@pytest.mark.parametrize("failure", ["split", "twse", "tpex"])
def test_failed_sync_retries_next_call_then_skips_all_sources(factory, monkeypatch, failure):
    fm = Mock(return_value=[split(), split("unknown")])
    twse = Mock(return_value=[])
    tpex = Mock(return_value=[])
    selected = {"split": fm, "twse": twse, "tpex": tpex}[failure]
    selected.side_effect = RuntimeError("secret-token")
    monkeypatch.setattr(FinMindClient, "get_price_events", fm)
    client = Mock(price_events=twse, tpex_price_events=tpex)
    result = sync_market_price_events(factory, BEFORE, DAY, client=client)
    assert not result.complete
    assert "secret-token" not in str(result.warnings)
    with factory() as db:
        assert not db.get(StockPriceEventSync, 1).complete
    selected.side_effect = None
    result = sync_market_price_events(factory, BEFORE, DAY, client=client)
    assert result.complete
    counts = (fm.call_count, twse.call_count, tpex.call_count)
    result = sync_market_price_events(factory, date(2011, 1, 1), DAY, client=client)
    assert result.complete
    assert (fm.call_count, twse.call_count, tpex.call_count) == counts
    assert fm.call_count == 2
    assert fm.call_args.kwargs["start_date"] == date(2011, 1, 1)
    with factory() as db:
        assert db.get(StockPriceEventSync, 1).complete
        assert list(db.scalars(select(StockPriceEvent.ticker))) == ["1"]


def test_split_long_holding_return_269_percent():
    from app.backtest.costs_benchmark import benchmark_return
    from app.backtest.simulation import adjusted_bars
    from app.conditions.types import ConditionBar

    final = DAY + timedelta(days=365)
    bars = [
        ConditionBar(BEFORE, 188.65, 188.65, 188.65, 188.65, 100),
        ConditionBar(DAY, 47.16, 47.16, 47.16, 47.16, 100),
        ConditionBar(final, 174.28, 174.28, 174.28, 174.28, 100),
    ]
    adjusted = adjusted_bars(bars, [PriceEvent(DAY, 188.65, 47.16)])
    benchmark = {b.trade_date.isoformat(): dict(open=b.open, close=b.close) for b in adjusted}
    assert benchmark_return(benchmark, BEFORE.isoformat(), final.isoformat(), "close") == (
        pytest.approx(2.6955, abs=0.0001)
    )


def test_concurrent_jobs_share_single_fetch(factory, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    entered, release = Event(), Event()

    def fetch(**kwargs):
        entered.set()
        assert release.wait(5)
        return []

    fm = Mock(side_effect=fetch)
    monkeypatch.setattr(FinMindClient, "get_price_events", fm)
    client = Mock(price_events=Mock(return_value=[]), tpex_price_events=Mock(return_value=[]))
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(sync_market_price_events, factory, BEFORE, DAY, client=client)
        assert entered.wait(5)
        second = pool.submit(sync_market_price_events, factory, BEFORE, DAY, client=client)
        release.set()
        assert first.result().complete
        assert second.result().complete
    fm.assert_called_once()
    client.price_events.assert_called_once()
    client.tpex_price_events.assert_called_once()


def test_write_failure_rolls_back_events_and_completion(factory, monkeypatch):
    monkeypatch.setattr(FinMindClient, "get_price_events", Mock(return_value=[split()]))
    client = Mock(price_events=Mock(return_value=[]), tpex_price_events=Mock(return_value=[]))
    original = MarketDataService.import_price_events

    def fail(self, ticker, rows):
        original(self, ticker, rows)
        raise RuntimeError("secret-token")

    monkeypatch.setattr(MarketDataService, "import_price_events", fail)
    result = sync_market_price_events(factory, BEFORE, DAY, client=client)
    assert not result.complete
    assert "secret-token" not in str(result.warnings)
    with factory() as db:
        assert not db.get(StockPriceEventSync, 1).complete
        assert db.scalar(select(StockPriceEvent)) is None
    monkeypatch.setattr(MarketDataService, "import_price_events", original)
    assert sync_market_price_events(factory, BEFORE, DAY, client=client).complete
