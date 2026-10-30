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

DEFAULT_PARAMS = {condition: dict(params) for condition, params in ORIGINAL_DEFAULTS.items()}
DEFAULT_PARAMS["ma_rising"]["min_slope_pct"] = 0.005
DEFAULT_PARAMS["ma_touch_rebound"]["max_close_distance_pct"] = 0.03

ORIGINAL_NOTES: dict[str, dict[str, str]] = {
    "ma_rising": {"min_slope_pct": "未給數值（要求有斜率）"},
    "ma_touch_rebound": {"max_close_distance_pct": "未給數值（要求回到月線附近）"},
    "close_below_ma_days": {
        "buffer": "0% = 原文（收盤跌破月線即算）；2% = 容許小幅跌破，減少被洗出場，但出場較晚",
    },
}
