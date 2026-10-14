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
