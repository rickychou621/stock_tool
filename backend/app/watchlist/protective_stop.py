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
        return {
            "price": float(ticks_below(ma, ticks, kind)),
            "ma": float(ma),
            "tick": float(tick_size(ma, kind)),
            "ticks": ticks,
        }
    return None
