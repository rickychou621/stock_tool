"""Derive the daily protective stop from the exit condition's latest moving average."""

from decimal import Decimal

from app.market_data.ticks import tick_size, ticks_below
from app.rules.evaluation import RuleEvaluationResult


def protective_stop(result: RuleEvaluationResult, kind: str, ticks: int = 3) -> dict | None:
    for condition in result.condition_results:
        if condition.role != "exit" or condition.condition_id != "close_below_ma_days":
            continue
        value = condition.indicators.get("ma")
        if value is None:
            continue
        ma = Decimal(str(value))
        buffer = Decimal(str(condition.indicators.get("buffer", 0)))
        base = ma * (Decimal("1") - buffer)
        close = condition.indicators.get("close")
        return {
            # Saved evaluations do not keep condition indicators, so carry the close here.
            "close": float(close) if close is not None else None,
            "price": float(ticks_below(base, ticks, kind)),
            "ma": float(ma),
            "buffer": float(buffer),
            "tick": float(tick_size(base, kind)),
            "ticks": ticks,
        }
    return None
