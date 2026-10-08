from datetime import date, timedelta

from app.conditions.bollinger_band import BollingerMidUpCondition
from app.conditions.ema_cross import EmaGoldenCrossCondition
from app.conditions.kd_macd import (
    KdGoldenCrossCondition,
    MacdHistogramRisingCondition,
    MacdPositiveCondition,
)
from app.conditions.types import ConditionBar
from app.conditions.volume_spike import VolumeSpikeCondition


def _bar(day_offset: int, close: float, volume: int = 1000, high: float | None = None,
         low: float | None = None) -> ConditionBar:
    trade_date = date(2026, 1, 1) + timedelta(days=day_offset)
    return ConditionBar(
        trade_date=trade_date,
        open=close,
        high=high if high is not None else close,
        low=low if low is not None else close,
        close=close,
        volume=volume,
    )


def _monthly_bar(month_offset: int, close: float) -> ConditionBar:
    # 用「每個月固定第1天各一根K」來湊出月K序列，resample_to_monthly後一個月剛好一根。
    year = 2026 + (month_offset // 12)
    month = (month_offset % 12) + 1
    return ConditionBar(
        trade_date=date(year, month, 1), open=close, high=close, low=close, close=close, volume=1000
    )


def test_ema_golden_cross_not_enough_data() -> None:
    bars = [_bar(i, 100) for i in range(3)]
    result = EmaGoldenCrossCondition().evaluate(bars, {"short_period": 3, "long_period": 5})
    assert result.is_met is False
    assert "不足" in result.reason


def test_ema_golden_cross_detects_upward_cross() -> None:
    closes = [100.0] * 6 + [150.0]
    bars = [_bar(i, c) for i, c in enumerate(closes)]
    result = EmaGoldenCrossCondition().evaluate(bars, {"short_period": 3, "long_period": 5})
    assert result.is_met is True


def test_ema_golden_cross_no_cross_on_flat_series() -> None:
    bars = [_bar(i, 100.0) for i in range(10)]
    result = EmaGoldenCrossCondition().evaluate(bars, {"short_period": 3, "long_period": 5})
    assert result.is_met is False


def test_bollinger_mid_up_not_enough_data() -> None:
    bars = [_bar(i, 100.0) for i in range(4)]
    result = BollingerMidUpCondition().evaluate(bars, {"period": 3, "slope_lookback": 2})
    assert result.is_met is False
    assert "不足" in result.reason


def test_bollinger_mid_up_true_when_mid_rising_and_price_in_band() -> None:
    # 持續小幅上漲：中軌會上揚，且股價貼著中軌之上，不會衝出上軌。
    closes = [10.0, 10.2, 10.4, 10.6, 10.8, 11.0, 11.2, 11.4]
    bars = [_bar(i, c) for i, c in enumerate(closes)]
    result = BollingerMidUpCondition().evaluate(bars, {"period": 3, "slope_lookback": 2})
    assert result.is_met is True
    assert "上揚" in result.reason


def test_bollinger_mid_up_false_when_mid_falling() -> None:
    closes = [20.0, 19.0, 18.0, 17.0, 16.0, 15.0, 14.0, 13.0]
    bars = [_bar(i, c) for i, c in enumerate(closes)]
    result = BollingerMidUpCondition().evaluate(bars, {"period": 3, "slope_lookback": 2})
    assert result.is_met is False
    assert "下彎" in result.reason


def test_bollinger_mid_up_false_when_price_drops_below_mid() -> None:
    # period拉大到5天，單日的小跌不會把5日中軌一起拖下去，才能單純測到「跌破中軌」這條路徑。
    closes = [10.0, 10.2, 10.4, 10.6, 10.8, 11.0, 11.2, 10.5]
    bars = [_bar(i, c) for i, c in enumerate(closes)]
    result = BollingerMidUpCondition().evaluate(bars, {"period": 5, "slope_lookback": 2})
    assert result.is_met is False
    assert "跌破月線" in result.reason


def test_bollinger_mid_up_true_when_price_blows_past_upper_band() -> None:
    # 前面長時間持平(波動小、上下軌很窄)，最後一天暴衝，才會真的衝出上軌而不是被自己拉寬。
    closes = [10.0] * 13 + [50.0]
    bars = [_bar(i, c) for i, c in enumerate(closes)]
    result = BollingerMidUpCondition().evaluate(bars, {"period": 10, "slope_lookback": 2})
    assert result.is_met is True
    assert "突破布林上軌" in result.reason
    assert result.upper_band_status == "breakout"


def test_bollinger_touch_is_reference_and_does_not_reject_rising_trend() -> None:
    # 最後3筆為12、12、12，中軌與上軌皆為12，高於兩日前中軌。
    bars = [_bar(i, c) for i, c in enumerate([10.0, 10.0, 12.0, 12.0, 12.0])]
    result = BollingerMidUpCondition().evaluate(bars, {"period": 3, "slope_lookback": 2})
    assert result.is_met is True
    assert result.upper_band_status == "touched"


def test_bollinger_intraday_touch_does_not_override_close_below_mid() -> None:
    closes = [10.0, 10.2, 10.4, 10.6, 10.8, 11.0, 11.2, 10.5]
    bars = [_bar(i, c, high=20.0 if i == 7 else c) for i, c in enumerate(closes)]
    result = BollingerMidUpCondition().evaluate(bars, {"period": 5, "slope_lookback": 2})
    assert result.is_met is False
    assert "跌破月線" in result.reason
    assert result.upper_band_status == "touched"


def test_kd_golden_cross_not_enough_monthly_data() -> None:
    bars = [_bar(i, 100.0) for i in range(5)]  # 只有一個月
    result = KdGoldenCrossCondition().evaluate(bars, {"period": 9})
    assert result.is_met is False
    assert "不足" in result.reason


def test_macd_positive_not_enough_monthly_data() -> None:
    bars = [_bar(i, 100.0) for i in range(5)]
    result = MacdPositiveCondition().evaluate(bars, {})
    assert result.is_met is False
    assert "不足" in result.reason


def test_macd_histogram_rising_not_enough_monthly_data() -> None:
    bars = [_monthly_bar(i, 100.0) for i in range(3)]
    result = MacdHistogramRisingCondition().evaluate(
        bars, {"short_period": 2, "long_period": 4, "signal_period": 2}
    )
    assert result.is_met is False
    assert "不足" in result.reason


def test_macd_histogram_rising_true_when_momentum_accelerating() -> None:
    # 漲幅一個月比一個月大(加速上漲)，動能持續增強，柱狀體應該持續放大。
    closes = [10.0, 11.0, 13.0, 16.0, 20.0, 25.0]
    bars = [_monthly_bar(i, c) for i, c in enumerate(closes)]
    result = MacdHistogramRisingCondition().evaluate(
        bars, {"short_period": 2, "long_period": 4, "signal_period": 2}
    )
    assert result.is_met is True
    assert "增加" in result.reason


def test_macd_histogram_rising_false_when_momentum_decelerating() -> None:
    # 漲幅一個月比一個月小(漲勢趨緩)，動能減弱，柱狀體應該持續縮小。
    closes = [10.0, 15.0, 19.0, 22.0, 24.0, 25.0]
    bars = [_monthly_bar(i, c) for i, c in enumerate(closes)]
    result = MacdHistogramRisingCondition().evaluate(
        bars, {"short_period": 2, "long_period": 4, "signal_period": 2}
    )
    assert result.is_met is False
    # 動能減弱有兩種可能的標籤：還是正值但縮小(紅柱縮減)，或轉成負值(綠柱擴張)，
    # 兩種都代表「不符合動能增強」，這裡只驗證不是「增加」這種改善的說法。
    assert "增加" not in result.reason


def test_volume_spike_detects_spike() -> None:
    bars = [_bar(i, 100.0, volume=1000) for i in range(20)]
    bars.append(_bar(20, 100.0, volume=5000))
    result = VolumeSpikeCondition().evaluate(bars, {"multiplier": 3, "lookback": 20})
    assert result.is_met is True


def test_volume_spike_no_spike_on_normal_volume() -> None:
    bars = [_bar(i, 100.0, volume=1000) for i in range(20)]
    bars.append(_bar(20, 100.0, volume=1200))
    result = VolumeSpikeCondition().evaluate(bars, {"multiplier": 3, "lookback": 20})
    assert result.is_met is False
