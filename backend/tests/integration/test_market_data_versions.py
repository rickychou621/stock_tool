# ruff: noqa: F811
from unittest.mock import Mock

import pytest
from sqlalchemy import select
from test_batch_market import raw
from test_market_scan import DAY, factory  # noqa: F401

from app.market_data.models import Stock
from app.market_data.service import MarketDataService


def versions(db):
    return dict(db.execute(select(Stock.ticker, Stock.data_version)).all())


def test_repeated_market_day_only_changes_revised_ticker(factory):
    with factory() as db:
        service = MarketDataService(db)
        rows = [raw(), raw(ticker="2")]
        service.import_market_day(DAY, rows)
        db.commit()
        before = versions(db)
        service.import_market_day(DAY, rows)
        db.commit()
        assert versions(db) == before
        service.import_market_day(DAY, [raw(close=11.05), raw(ticker="2")])
        db.commit()
        assert versions(db) == {**before, "1": before["1"] + 1}


@pytest.mark.parametrize("ranged", [False, True])
def test_sync_versions_track_prices_dividends_and_adjustments(factory, ranged):
    from datetime import timedelta
    from decimal import Decimal

    from app.market_data.models import StockPriceDaily

    previous = DAY - timedelta(days=1)
    client = Mock()
    client.get_daily_price.return_value = [
        {k: v for k, v in raw(day=day).items() if k != "ticker"} for day in (previous, DAY)
    ]
    client.get_dividend_events.return_value = []
    kwargs = dict(start_date=previous, end_date=DAY) if ranged else {}
    with factory() as db:
        service = MarketDataService(db, client)
        service.sync_daily_prices("1", **kwargs)
        before = versions(db)["1"]
        service.sync_daily_prices("1", **kwargs)
        assert versions(db)["1"] == before
        client.get_daily_price.return_value[1]["close"] = 11.05
        service.sync_daily_prices("1", **kwargs)
        assert versions(db)["1"] == before + 1
        client.get_dividend_events.return_value = [
            dict(
                ex_dividend_date=DAY,
                cash_dividend=1,
                stock_dividend_ratio=0,
                cash_capital_increase_ratio=0,
                cash_capital_increase_price=0,
            )
        ]
        service.sync_daily_prices("1", **kwargs)
        assert versions(db)["1"] == before + 2
        bar = db.scalar(select(StockPriceDaily).where(StockPriceDaily.trade_date == previous))
        assert bar.adj_close == Decimal("10.00")
        service.sync_daily_prices("1", **kwargs)
        assert versions(db)["1"] == before + 2
        bar.adj_close = 9
        db.commit()
        service.sync_daily_prices("1", **kwargs)
        assert versions(db)["1"] == before + 3
        client.get_daily_price.return_value[1]["volume"] += 1
        service.sync_daily_prices("1", **kwargs)
        assert versions(db)["1"] == before + 4


@pytest.mark.parametrize("ranged", [False, True])
@pytest.mark.parametrize("code,failures", [(1213, 2), (1205, 2), (1213, 4), (9999, 1)])
@pytest.mark.parametrize("stage", ["upsert_daily_bars", "upsert_dividend_events"])
def test_sync_retries_atomic_writes_without_refetch(
    factory, monkeypatch, ranged, code, failures, stage
):
    from sqlalchemy.exc import OperationalError

    from app.market_data import service as module
    from app.market_data.models import StockPriceDaily
    from app.market_data.repository import MarketDataRepository

    sleep = Mock()
    monkeypatch.setattr(module, "_sleep", sleep)
    monkeypatch.setattr(module.random, "uniform", lambda a, b: 0.5)
    original = getattr(MarketDataRepository, stage)
    attempts = []

    def write(self, ticker, rows):
        result = original(self, ticker, rows)
        attempts.append(ticker)
        if len(attempts) <= failures:
            raise OperationalError("write", {}, Exception(code, "simulated"))
        return result

    monkeypatch.setattr(MarketDataRepository, stage, write)
    client = Mock()
    client.get_daily_price.return_value = [{k: v for k, v in raw().items() if k != "ticker"}]
    client.get_dividend_events.return_value = []
    kwargs = dict(start_date=DAY, end_date=DAY) if ranged else {}
    with factory() as db:
        service = MarketDataService(db, client)
        if code == 9999 or failures == 4:
            with pytest.raises(OperationalError):
                service.sync_daily_prices("1", **kwargs)
            assert db.scalar(select(StockPriceDaily)) is None
            assert versions(db)["1"] == 0
            assert len(attempts) == failures
            assert sleep.call_count == failures - 1
        else:
            assert service.sync_daily_prices("1", **kwargs) == 1
            assert db.scalar(select(StockPriceDaily.close)) == 11
            assert versions(db)["1"] == 1
            assert len(attempts) == 3
            assert [c.args[0] for c in sleep.call_args_list] == [0.5, 1.0]
    client.get_daily_price.assert_called_once()
    client.get_dividend_events.assert_called_once()


def test_market_import_after_sync_preserves_adjusted_history_and_versions(factory, monkeypatch):
    from datetime import timedelta
    from decimal import Decimal

    from app.market_data.models import StockPriceDaily

    previous = DAY - timedelta(days=1)
    client = Mock()
    client.get_daily_price.return_value = [
        {k: v for k, v in raw(day=day).items() if k != "ticker"} for day in (previous, DAY)
    ]
    client.get_dividend_events.return_value = [
        dict(
            ex_dividend_date=DAY,
            cash_dividend=1,
            stock_dividend_ratio=0,
            cash_capital_increase_ratio=0,
            cash_capital_increase_price=0,
        )
    ]
    with factory() as db:
        service = MarketDataService(db, client)
        service.sync_daily_prices("1")
        before = versions(db)
        recalculate = Mock(wraps=service._recalculate_adjusted_prices)
        monkeypatch.setattr(service, "_recalculate_adjusted_prices", recalculate)
        service.import_market_day(previous, [raw(day=previous)])
        service.import_market_day(DAY, [raw()])
        db.commit()
        assert versions(db) == before
        recalculate.assert_not_called()
        bar = db.scalar(select(StockPriceDaily).where(StockPriceDaily.trade_date == previous))
        assert bar.adj_close == Decimal("10.00")
        service.import_market_day(DAY, [{**raw(), "volume": 12346}])
        db.commit()
        assert versions(db)["1"] == before["1"] + 1
        service.import_market_day(DAY, [{**raw(), "volume": 12346, "turnover": 135796}])
        db.commit()
        assert versions(db)["1"] == before["1"] + 2
        recalculate.assert_not_called()


def test_market_import_counts_adjustment_repair(factory):
    from app.market_data.models import StockPriceDaily

    with factory() as db:
        service = MarketDataService(db)
        service.import_market_day(DAY, [raw()])
        db.commit()
        before = versions(db)["1"]
        db.scalar(select(StockPriceDaily)).adj_close = None
        db.commit()
        service.import_market_day(DAY, [raw()])
        db.commit()
        assert versions(db)["1"] == before + 1
        assert db.scalar(select(StockPriceDaily.adj_close)) == 11
