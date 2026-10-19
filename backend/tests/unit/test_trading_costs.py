import copy

import pytest

from app.backtest.costs_benchmark import benchmark_return, enrich
from app.trading_costs import TradingCosts


@pytest.mark.parametrize("kind,tax", [("stock", 0.003), ("etf", 0.001)])
def test_fee_discount_and_sell_tax(kind, tax):
    costs = TradingCosts(fee_discount=0.6)
    expected = 110 * (1 - 0.001425 * 0.6 - tax) / (100 * (1 + 0.001425 * 0.6)) - 1
    assert costs.net_return(100, 110, kind) == pytest.approx(expected)
    assert TradingCosts.from_snapshot(costs.snapshot()) == costs


@pytest.mark.parametrize(
    "kwargs",
    [
        {"fee_discount": 0},
        {"fee_discount": 1.1},
        {"fee_rate": -1},
        {"tax_rate_etf": float("nan")},
        {"tax_rate_stock": 1},
        {"fee_rate": 0.6, "tax_rate_stock": 0.5},
    ],
)
def test_invalid_costs_rejected(kwargs):
    with pytest.raises(ValueError):
        TradingCosts(**kwargs)


def payload():
    return dict(
        actualStart="2026-10-01",
        actualEnd="2026-10-05",
        trades=[
            dict(
                status="closed",
                entryDate="2026-10-02",
                exitDate="2026-10-05",
                returnRate=0.001,
                unrealizedReturn=None,
            ),
            dict(
                status="open",
                entryDate="2026-10-05",
                exitDate=None,
                returnRate=None,
                unrealizedReturn=0.01,
            ),
            dict(
                status="unfilled",
                entryDate=None,
                exitDate=None,
                returnRate=None,
                unrealizedReturn=None,
            ),
        ],
    )


def test_net_statistics_benchmark_same_day_and_open_liquidation():
    bars = {
        "2026-10-01": dict(open=100, close=101),
        "2026-10-02": dict(open=102, close=103),
        "2026-10-05": dict(open=104, close=105),
    }
    costs = TradingCosts()
    result = enrich(payload(), costs.snapshot(), "stock", bars)
    closed, opened, unfilled = result["trades"]
    assert closed["grossReturnRate"] == 0.001
    assert closed["netReturnRate"] < 0  # Gross winner becomes net loser after costs.
    assert result["metrics"]["winRate"] == 0
    assert result["grossMetrics"]["winRate"] == 1
    assert result["metrics"]["compoundReturn"] == pytest.approx(closed["netReturnRate"])
    assert result["metrics"]["maxDrawdown"] == pytest.approx(-closed["netReturnRate"])
    assert closed["benchmarkReturn"] == pytest.approx(104 / 102 - 1)
    assert closed["excessReturn"] == pytest.approx(closed["netReturnRate"] - (104 / 102 - 1))
    assert result["averageExcessReturn"] == closed["excessReturn"]
    assert result["benchmarkBuyHoldReturn"] == pytest.approx(105 / 100 - 1)
    assert opened["netUnrealizedReturn"] == pytest.approx(costs.net_return(100, 101))
    assert unfilled["netReturnRate"] is None


def test_missing_benchmark_is_null_and_unknown_kind_disclosed():
    result = enrich(copy.deepcopy(payload()), TradingCosts().snapshot(), None, {})
    assert result["metrics"]["tradeCount"] == 1
    assert result["benchmarkBuyHoldReturn"] is None
    assert result["averageExcessReturn"] is None
    assert result["trades"][0]["benchmarkReason"]
    assert "普通股" in result["warnings"][0]
    assert (
        benchmark_return({"2026-10-02": dict(open=1, close=1)}, "2026-10-01", "2026-10-02") is None
    )
