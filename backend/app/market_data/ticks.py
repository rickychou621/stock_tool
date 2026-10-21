"""Taiwan stock/ETF price grids, calculated entirely with Decimal."""

from decimal import ROUND_FLOOR, Decimal

MIN_TICK = Decimal("0.01")


def tick_size(price: Decimal, kind: str) -> Decimal:
    if kind == "etf":
        return MIN_TICK if price < 50 else Decimal("0.05")
    for ceiling, tick in (
        (10, "0.01"), (50, "0.05"), (100, "0.1"),
        (500, "0.5"), (1000, "1"),
    ):
        if price < ceiling:
            return Decimal(tick)
    return Decimal("5")


def floor_to_tick(price: Decimal, kind: str) -> Decimal:
    tick = tick_size(price, kind)
    return (price / tick).to_integral_value(rounding=ROUND_FLOOR) * tick


def ticks_below(price: Decimal, n: int, kind: str) -> Decimal:
    """Floor first; each downward step uses the tier immediately below the price."""
    if n < 0:
        raise ValueError("n must be non-negative")
    current = floor_to_tick(price, kind)
    for _ in range(n):
        if current <= MIN_TICK:
            return MIN_TICK
        current -= tick_size(current.next_minus(), kind)
    return max(current, MIN_TICK)
