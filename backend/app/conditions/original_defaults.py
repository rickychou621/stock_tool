"""戰法原文參數；None 表示不限制。"""

ORIGINAL_DEFAULTS: dict[str, dict[str, float | int | None]] = {
    "ma_rising": {"period": 20, "slope_lookback": 5, "min_slope_pct": None},
    "ma_touch_rebound": {"period": 20, "tolerance": 0.01, "max_close_distance_pct": None},
    "close_below_ma_days": {"period": 20, "days": 2, "buffer": 0},
    "kd_golden_cross": {"period": 9, "max_k_at_cross": 70},
    "kd_high_death_cross": {"period": 9, "threshold": 70},
    "macd_positive": {"short_period": 12, "long_period": 26, "signal_period": 9},
    "macd_negative_any": {"short_period": 12, "long_period": 26, "signal_period": 9},
    "macd_histogram_rising": {"short_period": 12, "long_period": 26, "signal_period": 9},
}
