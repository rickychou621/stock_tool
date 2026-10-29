from typing import Any

from app.conditions.base import (
    Condition,
    ConditionResult,
    UpdateFrequency,
    insufficient_data_reason,
)
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
            return ConditionResult(
                False, insufficient_data_reason(bars, period + slope_lookback, len(bars)),
                data_sufficient=False,
            )

        ma = _ma_at(bars, period, len(bars))
        ma_prev = _ma_at(bars, period, len(bars) - slope_lookback)
        min_slope_pct = params.get("min_slope_pct")
        slope_pct = ma / ma_prev - 1 if ma_prev else 0.0
        is_met = (ma > ma_prev if min_slope_pct is None
                  else ma_prev != 0 and slope_pct >= float(min_slope_pct))
        status = "月線上揚" if is_met else "月線未上揚"
        comparison = ">" if is_met else "≤"
        reason = f"{status}（目前 {ma:.2f} {comparison} {slope_lookback} 日前 {ma_prev:.2f}）"
        if min_slope_pct is not None:
            reason = (f"月線斜率 {slope_pct:.2%}，門檻 ≥ {float(min_slope_pct):.2%}，"
                      + ("成立" if is_met else "未成立"))
        return ConditionResult(
            is_met, reason, indicators={"ma": ma, "ma_prev": ma_prev, "slope": ma - ma_prev,
                                      "slope_pct": slope_pct}
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
            return ConditionResult(
                False, insufficient_data_reason(bars, period, len(bars)),
                data_sufficient=False,
            )

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
        buffer = float(params.get("buffer", 0))
        if len(bars) < period + days - 1:
            return ConditionResult(
                False, insufficient_data_reason(bars, period + days - 1, len(bars)),
                data_sufficient=False,
            )

        ma = _ma_at(bars, period, len(bars))
        below_days = 0
        for offset in range(days):
            end = len(bars) - offset
            day_ma = ma if offset == 0 else _ma_at(bars, period, end)
            if bars[end - 1].close >= day_ma * (1 - buffer):
                break
            below_days += 1

        is_met = below_days == days
        reason = (
            f"連續 {days} 天收盤跌破月線" if is_met
            else f"收盤未連續跌破月線（連續 {below_days} 天）"
        )
        if buffer:
            reason = (f"連續 {days} 天收盤低於月線下方 {buffer * 100:g}%" if is_met
                      else f"收盤未連續 {days} 天低於月線下方 {buffer * 100:g}%"
                      f"（連續 {below_days} 天）")
        return ConditionResult(
            is_met, reason,
            indicators={"ma": ma, "close": bars[-1].close, "below_days": below_days,
                        "buffer": buffer},
        )


@register_condition
class MaTouchReboundCondition(Condition):
    id = "ma_touch_rebound"
    name = "回到月線後轉強"
    required_timeframe = "日K"
    update_frequency = UpdateFrequency.DAILY

    def evaluate(self, bars: list[ConditionBar], params: dict[str, Any]) -> ConditionResult:
        period = int(params.get("period", 20))
        tolerance = float(params.get("tolerance", 0.01))
        if len(bars) < period + 1:
            return ConditionResult(
                False, insufficient_data_reason(bars, period + 1, len(bars)),
                data_sufficient=False,
            )
        ma = _ma_at(bars, period, len(bars))
        prev_ma = _ma_at(bars, period, len(bars) - 1)
        previous, latest = bars[-2:]
        max_close_distance_pct = params.get("max_close_distance_pct")
        close_distance_pct = latest.close / ma - 1 if ma else 0.0
        is_met = (
            previous.low <= prev_ma * (1 + tolerance)
            and previous.close >= prev_ma
            and latest.close > previous.close
            and latest.close >= ma
        )
        if max_close_distance_pct is not None:
            is_met = is_met and ma != 0 and close_distance_pct <= float(max_close_distance_pct)
        reason = "回到月線後轉強" if is_met else "未回到月線後轉強"
        if max_close_distance_pct is not None:
            reason += (f"（收盤距月線 {close_distance_pct:.2%}，"
                       f"門檻 ≤ {float(max_close_distance_pct):.2%}）")
        return ConditionResult(
            is_met, reason,
            indicators={"ma": ma, "prev_ma": prev_ma, "close": latest.close,
                        "prev_close": previous.close, "close_distance_pct": close_distance_pct},
        )
