from typing import Any

from app.conditions.base import Condition, ConditionResult, UpdateFrequency
from app.conditions.indicators import calculate_kd, calculate_macd, resample_to_monthly
from app.conditions.registry import register_condition
from app.conditions.types import ConditionBar


@register_condition
class KdGoldenCrossCondition(Condition):
    id = "kd_golden_cross"
    name = "KD黃金交叉"
    required_timeframe = "月K"
    update_frequency = UpdateFrequency.MONTHLY

    def evaluate(self, bars: list[ConditionBar], params: dict[str, Any]) -> ConditionResult:
        period = int(params.get("period", 9))
        monthly = resample_to_monthly(bars)

        if len(monthly) < period + 1:
            return ConditionResult(False, "月K資料不足，無法判斷", data_sufficient=False)

        kd = calculate_kd(monthly, period)
        (prev_k, prev_d), (cur_k, cur_d) = kd[-2], kd[-1]

        crossed = prev_k <= prev_d and cur_k > cur_d
        state = "黃金交叉" if crossed else "未交叉"
        reason = f"月K K值={cur_k:.1f}，D值={cur_d:.1f}，{state}"
        return ConditionResult(crossed, reason)


@register_condition
class MacdPositiveCondition(Condition):
    id = "macd_positive"
    name = "MACD轉正"
    required_timeframe = "月K"
    update_frequency = UpdateFrequency.MONTHLY

    def evaluate(self, bars: list[ConditionBar], params: dict[str, Any]) -> ConditionResult:
        short_period = int(params.get("short_period", 12))
        long_period = int(params.get("long_period", 26))
        signal_period = int(params.get("signal_period", 9))
        monthly = resample_to_monthly(bars)

        # 月K資料量通常不會太多，門檻設成至少要有一整段長EMA週期的資料，
        # 不然DIF/MACD訊號線算出來的意義不大(目前追蹤的股票同步天數不夠長時，
        # 這個條件會持續回報「資料不足」，這是正確反映資料量不夠，不是bug)。
        if len(monthly) < long_period:
            return ConditionResult(False, "月K資料不足，無法判斷", data_sufficient=False)

        closes = [b.close for b in monthly]
        macd = calculate_macd(closes, short_period, long_period, signal_period)
        dif, signal = macd[-1]

        is_met = dif > 0 and signal > 0
        reason = f"月K DIF={dif:.2f}，MACD訊號線={signal:.2f}"
        return ConditionResult(is_met, reason)


def _histogram_label(current: float, previous: float) -> str:
    if current > previous:
        return "綠柱縮減" if current < 0 else "紅柱增加"
    return "紅柱縮減" if current > 0 else "綠柱擴張"


@register_condition
class MacdHistogramRisingCondition(Condition):
    """MACD柱狀體(DIF-訊號線)動能增強：綠柱縮減或紅柱增加，都代表動能正在轉強。"""

    id = "macd_histogram_rising"
    name = "MACD動能增強(柱狀體上升)"
    required_timeframe = "月K"
    update_frequency = UpdateFrequency.MONTHLY

    def evaluate(self, bars: list[ConditionBar], params: dict[str, Any]) -> ConditionResult:
        short_period = int(params.get("short_period", 12))
        long_period = int(params.get("long_period", 26))
        signal_period = int(params.get("signal_period", 9))
        monthly = resample_to_monthly(bars)

        if len(monthly) < long_period + 1:
            return ConditionResult(False, "月K資料不足，無法判斷", data_sufficient=False)

        closes = [b.close for b in monthly]
        macd = calculate_macd(closes, short_period, long_period, signal_period)
        histogram = [dif - signal for dif, signal in macd]

        current, previous = histogram[-1], histogram[-2]
        is_met = current > previous
        label = _histogram_label(current, previous)
        reason = f"MACD柱狀體{label}(本月{current:.2f}，上月{previous:.2f})"
        return ConditionResult(is_met, reason)
