from typing import Any

from app.conditions.base import Condition, ConditionResult, UpdateFrequency
from app.conditions.registry import register_condition
from app.conditions.types import ConditionBar


@register_condition
class VolumeSpikeCondition(Condition):
    id = "volume_spike"
    name = "爆量"
    required_timeframe = "日K"
    update_frequency = UpdateFrequency.DAILY

    def evaluate(self, bars: list[ConditionBar], params: dict[str, Any]) -> ConditionResult:
        multiplier = float(params.get("multiplier", 3))
        lookback = int(params.get("lookback", 20))

        if len(bars) < lookback + 1:
            return ConditionResult(False, "資料不足，無法判斷", data_sufficient=False)

        recent = bars[-(lookback + 1) : -1]  # 不含當天，取前lookback天
        avg_volume = sum(b.volume for b in recent) / lookback
        latest_volume = bars[-1].volume

        if avg_volume <= 0:
            return ConditionResult(False, "近期均量為0，無法判斷")

        ratio = latest_volume / avg_volume
        is_met = ratio > multiplier
        reason = f"今日成交量{latest_volume}，近{lookback}日均量{avg_volume:.0f}的{ratio:.1f}倍"
        return ConditionResult(is_met, reason)
