# ruff: noqa: F811 -- shared pytest fixture
from unittest.mock import Mock

import pytest
from sqlalchemy import select
from test_backtest_workflow import DATES, NOW, factory, payload, success  # noqa: F401

from app.backtest.costs_benchmark import load_benchmark
from app.backtest.models import BacktestResult, BacktestTask
from app.backtest.service import BacktestManager, read_report
from app.core.config import Settings
from app.market_data.models import Stock
from app.trading_costs import TradingCosts


def test_snapshot_persisted_and_legacy_not_mixed_with_net(factory, monkeypatch):
    settings = Settings(trade_fee_discount=0.6)
    monkeypatch.setattr("app.backtest.service.get_settings", lambda: settings)
    benchmark = Mock(
        return_value={
            "2026-10-08": dict(open=100, close=101),
            "2026-10-12": dict(open=102, close=103),
        }
    )
    job = BacktestManager(
        factory, calendar=lambda *args: DATES, worker=success, benchmark_loader=benchmark
    )
    job.start([1], now=NOW)
    job.close()
    benchmark.assert_called_once()
    settings.trade_fee_discount = 1
    with factory() as db:
        report = read_report(db)
        assert report["task"]["costSnapshot"]["feeDiscount"] == 0.6
        stock = report["stocks"][0]
        assert stock["metrics"]["averageReturn"] == TradingCosts(fee_discount=0.6).net_return(
            1, 1.1
        )
        assert stock["grossMetrics"]["averageReturn"] == 0.1
        assert report["overall"][0]["benchmarkBuyHoldReturn"] == 103 / 100 - 1
        row = db.scalar(select(BacktestResult))
        row.summary = payload(row.ticker)
        row.payload = payload(row.ticker)
        db.commit()
        report = read_report(db)
        legacy = next(s for s in report["stocks"] if s["id"] == row.id)
        assert legacy["needsRerun"]
        assert legacy["metrics"]["averageReturn"] is None
        assert legacy["grossMetrics"]["averageReturn"] == 0.1
        assert report["overall"][0]["stockCount"] == 1
        assert db.get(BacktestTask, 1).context_json["costSnapshot"]["feeDiscount"] == 0.6


def test_benchmark_missing_does_not_require_watchlist_or_fail_strategy(factory, monkeypatch):
    prepare = Mock(side_effect=ValueError("missing benchmark"))
    monkeypatch.setattr("app.backtest.costs_benchmark.prepare_data", prepare)
    assert load_benchmark(factory, DATES[0], DATES[-1], DATES) == {}
    prepare.assert_called_once()
    with factory() as db:
        assert db.scalar(select(Stock).where(Stock.ticker == "0050")) is not None


@pytest.fixture(autouse=True)
def isolate_market_event_http(monkeypatch):
    for method in ("price_events", "tpex_price_events"):
        monkeypatch.setattr(f"app.data_source.twse_client.TwseBatchClient.{method}", lambda *a: [])
    monkeypatch.setattr(
        "app.data_source.finmind_client.FinMindClient.get_price_events", lambda *a, **kw: []
    )
