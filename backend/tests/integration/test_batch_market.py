"""Stage-four A: real SQL transactions with mocked external sources."""
# ruff: noqa: F811 -- pytest fixture imported from the existing integration suite.

from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import Mock

import pytest
from sqlalchemy import event, select
from test_market_scan import DATES, DAY, bars, entry_bars, factory, rule, universe  # noqa: F401

from app.data_source import twse_client
from app.data_source.finmind_client import FinMindClient
from app.data_source.twse_client import DividendEvent, TwseBatchClient, parse_daily, parse_events
from app.market_data.models import Stock, StockDividendEvent, StockPriceDaily
from app.market_data.service import MarketDataService
from app.market_scan.batch_data import event_ranges, synchronize
from app.market_scan.models import BatchCoverage
from app.market_scan.rate_limit import RateLimiter
from app.market_scan.worker import evaluate_stock


@pytest.fixture(autouse=True)
def no_new_price_sources(monkeypatch):
    # These existing cases isolate dividends/quotes; dedicated price-event tests
    # exercise the new HTTP sources separately.
    monkeypatch.setattr(FinMindClient, "get_price_events", lambda *a, **kw: [])


def source(day=DAY, cells=None):
    return {
        "stat": "OK",
        "date": day.strftime("%Y%m%d"),
        "tables": [
            {"fields": ["其他"], "data": []},
            {
                "fields": [
                    "證券代號",
                    "開盤價",
                    "最高價",
                    "最低價",
                    "收盤價",
                    "成交股數",
                    "成交金額",
                ],
                "data": cells or [["1", "1,000", "1,100", "900", "1,050", "12,345", "12,345,000"]],
            },
        ],
    }


def raw(day=DAY, ticker="1", close=11):
    return dict(
        ticker=ticker,
        trade_date=day,
        open=10,
        high=max(12, close),
        low=9,
        close=close,
        volume=12345,
        turnover=135795,
    )


def run(factory, client, kind="scan", dates=DATES[-6:]):
    return synchronize(
        factory, universe(None, None)[0], [rule()], kind, dates, Mock(), Mock(), client=client
    )


def test_named_table_decimal_shares_absent_invalid_and_inactive():
    payload = source(
        cells=[
            ["1", "1,000", "1,100", "900", "1,050", "12,345", "12,345,000"],
            ["2", "--", "--", "--", "--", "0", "0"],
            ["3", "10", "9", "8", "11", "100", "1000"],
            ["inactive", "1", "1", "1", "1", "1", "1"],
        ]
    )
    rows, absent, invalid = parse_daily(payload, DAY, {"1", "2", "3", "4"})
    assert len(rows) == 1
    assert rows[0]["open"] == Decimal("1000")
    assert rows[0]["volume"] == 12345  # shares, never multiply by 1000
    assert rows[0]["turnover"] == Decimal("12345000")
    assert absent == {"2", "4"}
    assert set(invalid) == {"3"}


@pytest.mark.parametrize("change", [{"stat": "尚未發布"}, {"date": "20261011"}])
def test_reject_wrong_source_date(change):
    with pytest.raises(ValueError, match="尚未取得"):
        parse_daily({**source(), **change}, DAY, {"1"})


def test_day_prices_adjustment_warning_and_atomic_rollback(factory, monkeypatch):
    previous = DAY - timedelta(days=1)
    with factory() as db:
        service = MarketDataService(db)
        service.import_market_day(previous, [raw(previous)])
        db.add(StockDividendEvent(ticker="1", ex_dividend_date=DAY, cash_dividend=1))
        db.commit()
        service.import_market_day(DAY, [raw()])
        db.commit()
        old = db.scalar(select(StockPriceDaily).where(StockPriceDaily.trade_date == previous))
        assert old.adj_close == Decimal("10")
        assert old.turnover == 135795
        warnings = service.import_market_day(DAY, [raw(close=12)])
        assert warnings[0][0] == "1"
        db.commit()
        version = db.scalar(select(Stock.data_version).where(Stock.ticker == "1"))
        monkeypatch.setattr(service, "_recalculate_adjusted_prices", Mock(side_effect=ValueError))
        with pytest.raises(ValueError):
            service.import_market_day(DAY, [raw(close=13), raw(ticker="2")])
        db.rollback()
        assert (
            db.scalar(
                select(StockPriceDaily.close).where(
                    StockPriceDaily.ticker == "1", StockPriceDaily.trade_date == DAY
                )
            )
            == 12
        )
        assert db.scalar(select(StockPriceDaily).where(StockPriceDaily.ticker == "2")) is None
        assert db.scalar(select(Stock.data_version).where(Stock.ticker == "1")) == version


def test_historical_import_does_not_rewrite_unchanged_adjusted_prices(factory):
    previous = DAY - timedelta(days=2)
    with factory() as db:
        service = MarketDataService(db)
        service.import_market_day(previous, [raw(previous)])
        db.add(StockDividendEvent(ticker="1", ex_dividend_date=DAY, cash_dividend=1))
        db.commit()
        service.import_market_day(DAY, [raw()])
        db.commit()
    updates = []

    def capture(conn, cursor, statement, *args):
        if statement.startswith("UPDATE stock_price_daily"):
            updates.append(statement)

    engine = factory.kw["bind"]
    event.listen(engine, "before_cursor_execute", capture)
    try:
        with factory() as db:
            MarketDataService(db).import_market_day(DAY, [raw()])
            db.commit()
            old = db.scalar(select(StockPriceDaily).where(StockPriceDaily.trade_date == previous))
            assert old.adj_open == Decimal("9.09")
            assert old.adj_close == Decimal("10.00")
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert updates == []


@pytest.mark.parametrize("with_event", [False, True])
def test_missing_historical_day_uses_known_future_dividends(factory, with_event):
    previous = DAY - timedelta(days=2)
    missing = DAY - timedelta(days=1)
    with factory() as db:
        service = MarketDataService(db)
        service.import_market_day(previous, [raw(previous)])
        if with_event:
            db.add(StockDividendEvent(ticker="1", ex_dividend_date=DAY, cash_dividend=1))
            db.commit()
        service.import_market_day(DAY, [raw()])
        db.commit()
        service.import_market_day(missing, [raw(missing, close=12)])
        db.commit()
        inserted = db.scalar(select(StockPriceDaily).where(StockPriceDaily.trade_date == missing))
        earlier = db.scalar(select(StockPriceDaily).where(StockPriceDaily.trade_date == previous))
        assert inserted.adj_close == Decimal("11.00" if with_event else "12.00")
        assert earlier.adj_close == Decimal("10.08" if with_event else "11.00")


def test_six_days_batch_then_only_new_day_and_absence_is_cached(factory):
    client = Mock(price_events=Mock(return_value=[]), tpex_price_events=Mock(return_value=[]))
    client.events.return_value = []
    client.daily.side_effect = lambda day, active: ([raw(day)], {"2"}, {})
    warnings, errors = run(factory, client)
    assert not errors
    assert client.daily.call_count == 6
    assert "MI_INDEX 6 次" in warnings[-1]
    run(factory, client)
    assert client.daily.call_count == 6
    run(factory, client, dates=[*DATES[-5:], DAY + timedelta(days=1)])
    assert client.daily.call_count == 7
    assert client.events.call_count == 3


def test_invalid_is_not_confirmed_absent_and_write_failure_has_no_coverage(factory, monkeypatch):
    client = Mock(price_events=Mock(return_value=[]), tpex_price_events=Mock(return_value=[]))
    client.events.return_value = []
    client.daily.return_value = ([raw()], set(), {"2": "無效 OHLC"})
    run(factory, client, dates=[DAY])
    _, errors = run(factory, client, dates=[DAY])
    assert client.daily.call_count == 2
    assert errors[0][0] == "2"
    monkeypatch.setattr(MarketDataService, "import_market_day", Mock(side_effect=RuntimeError))
    next_day = DAY + timedelta(days=1)
    client.daily.return_value = ([raw(next_day)], {"2"}, {})
    warnings, _ = run(factory, client, dates=[next_day])
    assert "寫入失敗" in warnings[0]
    with factory() as db:
        assert db.get(BatchCoverage, next_day) is None
        assert (
            db.scalar(select(StockPriceDaily).where(StockPriceDaily.trade_date == next_day)) is None
        )


def test_unpublished_no_retry_or_finmind_fallback_and_older_quote(factory, monkeypatch):
    client = Mock(price_events=Mock(return_value=[]), tpex_price_events=Mock(return_value=[]))
    client.events.return_value = []
    client.daily.side_effect = ValueError("未發布")
    finmind = Mock(side_effect=AssertionError("must not fetch per-stock prices"))
    monkeypatch.setattr(FinMindClient, "get_daily_price", finmind)
    with factory() as db:
        db.add_all(entry_bars(days=DATES[:-1]))
        db.commit()
    warnings, _ = run(factory, client, dates=[DAY])
    assert client.daily.call_count == 1
    finmind.assert_not_called()
    assert "尚未取得" in warnings[0]
    with factory() as db:
        result = evaluate_stock(
            "1", "股票1", "stock", [rule()], list(db.scalars(select(StockPriceDaily))), DATES
        )
        assert result.candidates[0]["older_quote"] is True


def test_initialization_reuses_valid_prices_and_monthly_events(factory):
    client = Mock(price_events=Mock(return_value=[]), tpex_price_events=Mock(return_value=[]))
    client.events.return_value = []
    client.daily.side_effect = lambda day, active: ([raw(day, t) for t in active], set(), {})
    with factory() as db:
        db.add_all(bars(days=DATES[:1]))
        db.commit()
    run(factory, client, kind="initialize", dates=DATES[:2])
    with factory() as db:
        old = db.scalar(
            select(StockPriceDaily).where(
                StockPriceDaily.trade_date == DATES[0], StockPriceDaily.ticker == "1"
            )
        )
        assert old.volume == 0  # existing valid row was reused, not overwritten
    client.daily.reset_mock()
    run(factory, client, kind="initialize", dates=DATES[:2])
    client.daily.assert_not_called()
    assert event_ranges([date(2026, 1, 30), date(2026, 3, 2)], "initialize") == [
        (date(2026, 1, 30), date(2026, 1, 31)),
        (date(2026, 2, 1), date(2026, 2, 28)),
        (date(2026, 3, 1), date(2026, 3, 2)),
    ]


def test_events_only_missing_active_stock_and_mismatch_warning(factory, monkeypatch):
    with factory() as db:
        db.add(StockDividendEvent(ticker="1", ex_dividend_date=DAY, cash_dividend=1))
        db.commit()
    client = Mock(price_events=Mock(return_value=[]), tpex_price_events=Mock(return_value=[]))
    client.events.return_value = [
        DividendEvent(t, DAY, "權", Decimal(1)) for t in ("1", "2", "inactive")
    ]
    client.daily.return_value = ([], {"1", "2"}, {})
    sync = Mock()
    monkeypatch.setattr(MarketDataService, "sync_daily_prices", sync)
    _, errors = run(factory, client, dates=[DAY])
    sync.assert_called_once_with("2", start_date=DAY, end_date=DAY, fetch_prices=False)
    assert any(t == "2" and "無對應除權息日" in reason for t, reason in errors)


def test_http_queries_shared_pacing_html_no_retry(respx_mock, monkeypatch):
    now = [0.0]
    limiter = RateLimiter(20, clock=lambda: now[0], sleep=lambda d: now.__setitem__(0, now[0] + d))
    monkeypatch.setattr(twse_client, "shared_limiter", lambda: limiter)
    events = respx_mock.get(twse_client.BASE + "TWT49U").respond(
        200,
        json={
            "stat": "OK",
            "fields": ["股票代號", "資料日期", "權/息", "權值+息值"],
            "data": [["1", "115年10月12日", "權", "1"]],
        },
    )
    assert TwseBatchClient().events(DAY, DAY) == [DividendEvent("1", DAY, "權", Decimal(1))]
    assert events.calls.last.request.url.params["startDate"] == "20261012"
    assert events.calls.last.request.url.params["endDate"] == "20261012"
    mi = respx_mock.get(twse_client.BASE + "MI_INDEX").respond(200, text="<html>blocked</html>")
    with pytest.raises(ValueError):
        TwseBatchClient().daily(DAY, {"1"})
    assert mi.call_count == 1
    for url in (twse_client.BASE + "FMTQIK", "https://isin.twse.com.tw/isin/C_public.jsp"):
        respx_mock.get(url).respond(200, text="OK")
        twse_client.get(url)
    assert now[0] == 12


@pytest.mark.parametrize("token", ["", "private-test-token"])
def test_finmind_bearer_token_and_sanitized_error(respx_mock, monkeypatch, token):
    from types import SimpleNamespace

    monkeypatch.setattr(
        "app.data_source.finmind_client.get_settings",
        lambda: SimpleNamespace(finmind_api_token=token),
    )
    route = respx_mock.get("https://api.finmindtrade.com/api/v4/data").respond(
        200, json={"status": 200, "data": []}
    )
    FinMindClient().get_daily_price("2330", start_date=DAY, end_date=DAY)
    request = route.calls.last.request
    assert request.headers.get("Authorization") == (f"Bearer {token}" if token else None)
    assert "token" not in request.url.params
    route.respond(403, json={"status": 403, "msg": token})
    with pytest.raises(RuntimeError) as error:
        FinMindClient().get_daily_price("2330", start_date=DAY, end_date=DAY)
    assert not token or token not in str(error.value)


def test_prices_only_never_requests_dividends(factory):
    client = Mock(price_events=Mock(return_value=[]), tpex_price_events=Mock(return_value=[]))
    client.daily.return_value = ([raw()], {"2"}, {})
    synchronize(
        factory,
        universe(None, None)[0],
        [rule()],
        "initialize",
        [DAY],
        Mock(),
        Mock(),
        client=client,
        mode="prices",
    )
    client.events.assert_not_called()
    assert client.daily.call_count == 1


def test_dividends_aggregate_months_one_call_per_stock(factory, monkeypatch):
    from app.market_scan.models import DividendCoverage

    days = [date(2026, 8, 3), date(2026, 9, 3), DAY]
    client = Mock(price_events=Mock(return_value=[]), tpex_price_events=Mock(return_value=[]))
    client.events.side_effect = [[DividendEvent("1", day, "權", Decimal(1))] for day in days]
    calls = []

    def sync(self, ticker, **kwargs):
        calls.append((ticker, kwargs))
        for day in days:
            self._db.add(StockDividendEvent(ticker=ticker, ex_dividend_date=day, cash_dividend=1))
        self._db.commit()

    monkeypatch.setattr(MarketDataService, "sync_daily_prices", sync)
    synchronize(
        factory,
        universe(None, None)[0],
        [rule()],
        "initialize",
        days,
        Mock(),
        Mock(),
        client=client,
        mode="dividends",
    )
    assert calls == [
        (
            "1",
            dict(
                start_date=days[0],
                end_date=days[-1],
                fetch_prices=False,
            ),
        )
    ]
    client.daily.assert_not_called()
    with factory() as db:
        assert db.get(DividendCoverage, "1").start_date == days[0]
        assert db.get(DividendCoverage, "2").end_date == DAY


def test_missing_dividends_cannot_publish_normal_match(factory):
    from app.market_scan.models import DividendCoverage
    from app.market_scan.worker import process_stock

    with factory() as db:
        db.add_all(bars())
        db.commit()
    item = universe(None, None)[0][0]
    result = process_stock(factory, item, [rule()], "scan", DATES, Mock())
    assert not result.candidates
    assert "還原資料未完整" in result.errors[0][2]
    with factory() as db:
        db.add(DividendCoverage(ticker="1", start_date=DATES[0], end_date=DAY))
        db.commit()
    assert process_stock(factory, item, [rule()], "scan", DATES, Mock()).succeeded


def test_failed_event_detection_never_marks_complete(factory):
    from app.market_scan.models import DividendCoverage

    client = Mock(price_events=Mock(return_value=[]), tpex_price_events=Mock(return_value=[]))
    client.events.side_effect = ValueError("source unavailable")
    warnings, _ = synchronize(
        factory,
        universe(None, None)[0],
        [rule()],
        "initialize",
        [DAY],
        Mock(),
        Mock(),
        client=client,
        mode="dividends",
    )
    with factory() as db:
        assert db.get(DividendCoverage, "1") is None
    assert any("還原資料未完整" in w for w in warnings)
    client.daily.assert_not_called()


def test_missing_finmind_event_is_not_marked_complete(factory, monkeypatch):
    from app.market_scan.models import DividendCoverage

    client = Mock(price_events=Mock(return_value=[]), tpex_price_events=Mock(return_value=[]))
    client.events.return_value = [DividendEvent("1", DAY, "權", Decimal(1))]
    monkeypatch.setattr(MarketDataService, "sync_daily_prices", Mock())
    synchronize(
        factory,
        universe(None, None)[0],
        [rule()],
        "initialize",
        [DAY],
        Mock(),
        Mock(),
        client=client,
        mode="dividends",
    )
    with factory() as db:
        assert db.get(DividendCoverage, "1") is None
        assert db.get(DividendCoverage, "2") is not None


@pytest.mark.parametrize(
    "kind,cash,expected",
    [
        ("息", 0, "1.07"),
        ("息", None, "1.07"),
        ("權", None, None),
        ("權息", None, None),
        ("息", 2, "2.00"),
    ],
)
def test_twse_cash_fallback(factory, respx_mock, monkeypatch, kind, cash, expected):
    from app.market_scan.models import DividendCoverage

    monkeypatch.setattr(twse_client, "shared_limiter", lambda: Mock())
    monkeypatch.setattr(TwseBatchClient, "price_events", lambda *a: [])
    monkeypatch.setattr(TwseBatchClient, "tpex_price_events", lambda *a: [])
    respx_mock.get(twse_client.BASE + "TWT49U").respond(
        200,
        json={
            "stat": "OK",
            "fields": ["權值+息值", "股票代號", "權/息", "資料日期"],
            "data": [["1.07", "1", kind, "115年10月12日"]],
        },
    )
    finmind = respx_mock.get("https://api.finmindtrade.com/api/v4/data").respond(
        200,
        json={
            "status": 200,
            "data": []
            if cash is None
            else [
                {
                    "CashExDividendTradingDate": DAY.isoformat(),
                    "CashEarningsDistribution": cash,
                }
            ],
        },
    )
    previous = DAY - timedelta(days=1)
    with factory() as db:
        service = MarketDataService(db)
        service.import_market_day(previous, [raw(previous)])
        service.import_market_day(DAY, [raw()])
        db.commit()
    warnings, errors = synchronize(
        factory,
        universe(None, None)[0],
        [rule()],
        "initialize",
        [previous, DAY],
        Mock(),
        Mock(),
        client=TwseBatchClient(),
        mode="dividends",
    )
    assert finmind.call_count == 1
    with factory() as db:
        saved = db.scalar(select(StockDividendEvent).where(StockDividendEvent.ticker == "1"))
        coverage = db.get(DividendCoverage, "1")
        if expected is None:
            assert saved is None and coverage is None
            assert any("無對應除權息日" in reason for _, reason in errors)
            assert any("還原資料未完整" in warning for warning in warnings)
        else:
            assert saved.cash_dividend == Decimal(expected)
            assert saved.stock_dividend_ratio == saved.cash_capital_increase_ratio == 0
            assert saved.cash_capital_increase_price == 0
            assert coverage.start_date == previous and coverage.end_date == DAY
            old = db.scalar(select(StockPriceDaily).where(StockPriceDaily.trade_date == previous))
            assert old.adj_close == Decimal(11) - Decimal(expected)
            assert not any("還原資料未完整" in warning for warning in warnings)
            if cash:
                assert not errors
            else:
                assert errors == [("1", f"{DAY} FinMind 無配息資料，改用證交所息值 1.07")]
                # Later authoritative FinMind data overwrites the fallback through the same upsert.
                finmind.respond(
                    200,
                    json={
                        "status": 200,
                        "data": [
                            {
                                "CashExDividendTradingDate": DAY.isoformat(),
                                "CashEarningsDistribution": 2,
                            }
                        ],
                    },
                )
                MarketDataService(db).sync_daily_prices(
                    "1",
                    start_date=DAY,
                    end_date=DAY,
                    fetch_prices=False,
                )
                db.refresh(saved)
                db.refresh(old)
                assert saved.cash_dividend == 2 and old.adj_close == 9


def test_event_value_parses_thousands_by_field_name():
    assert parse_events(
        {
            "stat": "OK",
            "fields": ["權/息", "資料日期", "權值+息值", "股票代號"],
            "data": [["息", "115年10月12日", "1,234.56", "1"]],
        },
        DAY,
        DAY,
    ) == [DividendEvent("1", DAY, "息", Decimal("1234.56"))]


def test_no_trade_is_confirmed_without_refetch(factory):
    from app.market_scan.data import missing_ranges
    from app.market_scan.worker import process_stock

    with factory() as db:
        rows = bars(days=DATES[-3:])
        zero = rows[1]
        for key in ("open", "high", "low", "close"):
            setattr(zero, key, 0)
            setattr(zero, "adj_" + key, None)
        db.add_all(rows)
        db.add(BatchCoverage(trade_date=zero.trade_date, absent_tickers=["2"]))
        db.commit()
        assert missing_ranges(DATES[-3:], rows, []) == []
    client = Mock(price_events=Mock(return_value=[]), tpex_price_events=Mock(return_value=[]))
    client.events.return_value = []
    run(factory, client, dates=[zero.trade_date])
    client.daily.assert_not_called()
    result = process_stock(
        factory, universe(None, None)[0][0], [rule()], "initialize", DATES[-3:], Mock()
    )
    assert result.succeeded and not result.failed
