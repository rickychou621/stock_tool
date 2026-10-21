from decimal import Decimal

import pytest

from app.market_data.ticks import floor_to_tick, tick_size, ticks_below


@pytest.mark.parametrize(
    "price,stock,etf",
    [
        ("9.99", "0.01", "0.01"), ("10", "0.05", "0.01"),
        ("49.95", "0.05", "0.01"), ("50", "0.1", "0.05"),
        ("99.9", "0.1", "0.05"), ("100", "0.5", "0.05"),
        ("499.5", "0.5", "0.05"), ("500", "1", "0.05"),
        ("999", "1", "0.05"), ("1000", "5", "0.05"),
    ],
)
def test_tick_tiers(price, stock, etf):
    assert tick_size(Decimal(price), "stock") == Decimal(stock)
    assert tick_size(Decimal(price), "unknown") == Decimal(stock)
    assert tick_size(Decimal(price), "etf") == Decimal(etf)


@pytest.mark.parametrize(
    "price,kind,floored,stop",
    [
        ("2493.0", "stock", "2490", "2475"),
        ("24.68", "stock", "24.65", "24.50"),
        ("57.61", "etf", "57.60", "57.45"),
        # 50.05 floors to 50.00, then 49.95 -> 49.90 -> 49.85.
        ("50.05", "stock", "50.00", "49.85"),
        ("10", "stock", "10", "9.97"),
        ("100", "stock", "100", "99.7"),
        ("500", "stock", "500", "498.5"),
        ("1000", "stock", "1000", "997"),
        ("50", "etf", "50", "49.97"),
    ],
)
def test_floor_and_three_ticks(price, kind, floored, stop):
    assert floor_to_tick(Decimal(price), kind) == Decimal(floored)
    assert ticks_below(Decimal(price), 3, kind) == Decimal(stop)


@pytest.mark.parametrize("kind", ["stock", "etf"])
@pytest.mark.parametrize("price", ["0", "0.001", "0.01", "0.02", "0.03"])
def test_minimum_positive_price(price, kind):
    assert ticks_below(Decimal(price), 3, kind) == Decimal("0.01")


def test_zero_and_negative_steps():
    assert ticks_below(Decimal("24.68"), 0, "stock") == Decimal("24.65")
    with pytest.raises(ValueError):
        ticks_below(Decimal("24.68"), -1, "stock")
