"""Shared numeric bar validity; zero volume alone is not corrupt data."""

import math


def valid_ohlcv(bar, adjusted=False):
    def value(key):
        return bar.get(key) if isinstance(bar, dict) else getattr(bar, key, None)

    prefix = "adj_" if adjusted else ""
    try:
        o, h, low, c = [float(value(prefix + k)) for k in ("open", "high", "low", "close")]
        volume = float(value("volume"))
        return all(math.isfinite(v) and v > 0 for v in (o, h, low, c)) and (
            h >= max(o, c)
            and low <= min(o, c)
            and h >= low
            and math.isfinite(volume)
            and volume >= 0
        )
    except (TypeError, ValueError):
        return False


def is_no_trade(bar):
    """A day without a regular-session trade: all prices zero, adjusted prices zero or missing.

    Volume is ignored on purpose. FinMind reports odd-lot or block-trade volume on days
    whose regular-session prices are all zero (5906 on 2026-10-16: 405 shares, OHLC 0).
    A zero price is never a valid fill, so such rows are no-trade days, not corrupt data.
    """

    def value(key):
        return bar.get(key) if isinstance(bar, dict) else getattr(bar, key, None)

    return all(value(k) == 0 for k in ("open", "high", "low", "close")) and all(
        value("adj_" + k) in (None, 0) for k in ("open", "high", "low", "close")
    )
