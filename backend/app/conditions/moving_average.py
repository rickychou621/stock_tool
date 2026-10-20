from typing import Any

from app.conditions.base import Condition, ConditionResult, UpdateFrequency
from app.conditions.registry import register_condition
from app.conditions.types import ConditionBar


def _ma_at(bars: list[ConditionBar], period: int, end: int) -> float:
    """只計算截至 end（不含）的 period 根收盤均價。"""
    return sum(bar.close for bar in bars[end - period : end]) / period


@register_condition
class MaRisingCondition(Condition):
    id = "ma_rising"
    name = "月線上揚"
    required_timeframe = "日K"
    update_frequency = UpdateFrequency.DAILY

    def evaluate(self, bars: list[ConditionBar], params: dict[str, Any]) -> ConditionResult:
        period = int(params.get("period", 20))
        slope_lookback = int(params.get("slope_lookback", 5))
        if len(bars) < period + slope_lookback:
            return ConditionResult(False, "資料不足，無法判斷", data_sufficient=False)

        ma = _ma_at(bars, period, len(bars))
        ma_prev = _ma_at(bars, period, len(bars) - slope_lookback)
        is_met = ma > ma_prev
        status = "月線上揚" if is_met else "月線未上揚"
        comparison = ">" if is_met else "≤"
        reason = f"{status}（目前 {ma:.2f} {comparison} {slope_lookback} 日前 {ma_prev:.2f}）"
        return ConditionResult(
            is_met, reason, indicators={"ma": ma, "ma_prev": ma_prev, "slope": ma - ma_prev}
        )


@register_condition
class PriceTouchMaCondition(Condition):
    id = "price_touch_ma"
    name = "回到月線"
    required_timeframe = "日K"
    update_frequency = UpdateFrequency.DAILY

    def evaluate(self, bars: list[ConditionBar], params: dict[str, Any]) -> ConditionResult:
        period = int(params.get("period", 20))
        tolerance = float(params.get("tolerance", 0.01))
        if len(bars) < period:
            return ConditionResult(False, "資料不足，無法判斷", data_sufficient=False)

        ma = _ma_at(bars, period, len(bars))
        latest = bars[-1]
        is_met = latest.low <= ma * (1 + tolerance) and latest.close >= ma
        status = "回到月線" if is_met else "未回到月線"
        reason = (
            f"{status}（最低價 {latest.low:.2f}、收盤 {latest.close:.2f}、"
            f"月線 {ma:.2f}，容許偏離 {tolerance:.2%}）"
        )
        return ConditionResult(
            is_met, reason,
            indicators={
                "ma": ma, "low": latest.low, "close": latest.close,
                "distance": latest.low / ma - 1,
            },
        )


@register_condition
class CloseBelowMaDaysCondition(Condition):
    id = "close_below_ma_days"
    name = "連續收盤跌破月線"
    required_timeframe = "日K"
    update_frequency = UpdateFrequency.DAILY

    def evaluate(self, bars: list[ConditionBar], params: dict[str, Any]) -> ConditionResult:
        period = int(params.get("period", 20))
        days = int(params.get("days", 2))
        if len(bars) < period + days - 1:
            return ConditionResult(False, "資料不足，無法判斷", data_sufficient=False)

        ma = _ma_at(bars, period, len(bars))
        below_days = 0
        for offset in range(days):
            end = len(bars) - offset
            day_ma = ma if offset == 0 else _ma_at(bars, period, end)
            if bars[end - 1].close >= day_ma:
                break
            below_days += 1

        is_met = below_days == days
        reason = (
            f"連續 {days} 天收盤跌破月線" if is_met
            else f"收盤未連續跌破月線（連續 {below_days} 天）"
        )
        return ConditionResult(
            is_met, reason,
            indicators={"ma": ma, "close": bars[-1].close, "below_days": below_days},
        )
