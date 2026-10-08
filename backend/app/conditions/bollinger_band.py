from typing import Any

from app.conditions.base import Condition, ConditionResult, UpdateFrequency
from app.conditions.indicators import calculate_bollinger_bands
from app.conditions.registry import register_condition
from app.conditions.types import ConditionBar


@register_condition
class BollingerMidUpCondition(Condition):
    id = "bollinger_mid_up"
    name = "布林上軌區間(月線上揚)"
    required_timeframe = "日K"
    update_frequency = UpdateFrequency.DAILY

    def evaluate(self, bars: list[ConditionBar], params: dict[str, Any]) -> ConditionResult:
        period = int(params.get("period", 20))
        num_std = float(params.get("num_std", 2))
        # 用幾天前的中軌來判斷月線斜率(上揚/下彎)，不是只看單一天的高低。
        slope_lookback = int(params.get("slope_lookback", 5))

        closes = [b.close for b in bars]
        if len(closes) < period + slope_lookback:
            return ConditionResult(False, "資料不足，無法判斷", data_sufficient=False)

        bands = calculate_bollinger_bands(closes, period, num_std)
        upper_now, mid_now, _ = bands[-1]  # 上面已確認資料筆數足夠，不會是None
        prev_band = bands[-1 - slope_lookback]
        assert prev_band is not None
        _, mid_prev, _ = prev_band

        latest_close = closes[-1]
        mid_rising = mid_now > mid_prev
        upper_status = None
        upper_note = ""
        if latest_close > upper_now:
            upper_status = "breakout"
            upper_note = f"；突破布林上軌{upper_now:.2f}（壓力參考，不影響符合判斷）"
        elif bars[-1].high >= upper_now:
            upper_status = "touched"
            upper_note = f"；當日最高價觸及布林上軌{upper_now:.2f}（壓力參考）"

        if not mid_rising:
            reason = (
                f"月線(中軌)下彎中，目前{mid_now:.2f}、{slope_lookback}日前{mid_prev:.2f}，"
                "非偏多格局"
            )
            return ConditionResult(False, reason + upper_note, upper_band_status=upper_status)

        if latest_close < mid_now:
            reason = f"股價{latest_close:.2f}已跌破月線{mid_now:.2f}，不在布林上軌區間"
            return ConditionResult(False, reason + upper_note, upper_band_status=upper_status)

        reason = (
            f"月線上揚(目前{mid_now:.2f} > {slope_lookback}日前{mid_prev:.2f})，"
            f"股價{latest_close:.2f}未跌破月線{mid_now:.2f}"
        )
        return ConditionResult(True, reason + upper_note, upper_band_status=upper_status)
