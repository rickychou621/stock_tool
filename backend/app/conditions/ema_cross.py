from typing import Any

from app.conditions.base import Condition, ConditionResult, UpdateFrequency
from app.conditions.indicators import calculate_ema
from app.conditions.registry import register_condition
from app.conditions.types import ConditionBar


@register_condition
class EmaGoldenCrossCondition(Condition):
    id = "ema_golden_cross"
    name = "EMA黃金交叉"
    # 理想上應該用分K，但目前還沒有券商即時盤中資料源(broker API暫緩)，
    # 先用日K還原股價近似，資料源接上即時資料後再切換。
    required_timeframe = "日K"
    update_frequency = UpdateFrequency.DAILY

    def evaluate(self, bars: list[ConditionBar], params: dict[str, Any]) -> ConditionResult:
        short_period = int(params.get("short_period", 10))
        long_period = int(params.get("long_period", 60))

        closes = [b.close for b in bars]
        if len(closes) < long_period + 2:
            return ConditionResult(False, "資料不足，無法判斷", data_sufficient=False)

        ema_short = calculate_ema(closes, short_period)
        ema_long = calculate_ema(closes, long_period)

        crossed = ema_short[-2] <= ema_long[-2] and ema_short[-1] > ema_long[-1]
        state = "向上黃金交叉" if crossed else "未交叉"
        reason = (
            f"{short_period}EMA={ema_short[-1]:.2f}，{long_period}EMA={ema_long[-1]:.2f}，{state}"
        )
        return ConditionResult(crossed, reason)
