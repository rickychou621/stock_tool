from datetime import date

from app.conditions.indicators import (
    calculate_bollinger_bands,
    calculate_ema,
    calculate_kd,
    calculate_macd,
    calculate_sma,
    resample_to_monthly,
)
from app.conditions.types import ConditionBar


def test_calculate_ema_first_value_equals_input() -> None:
    ema = calculate_ema([10.0, 12.0, 11.0], period=3)
    assert ema[0] == 10.0
    assert len(ema) == 3


def test_calculate_sma_needs_full_window() -> None:
    sma = calculate_sma([1.0, 2.0, 3.0, 4.0], period=3)
    assert sma[0] is None
    assert sma[1] is None
    assert sma[2] == 2.0  # (1+2+3)/3
    assert sma[3] == 3.0  # (2+3+4)/3


def test_calculate_bollinger_bands_needs_full_window() -> None:
    bands = calculate_bollinger_bands([1.0, 2.0, 3.0, 4.0], period=3, num_std=2)
    assert bands[0] is None
    assert bands[1] is None
    assert bands[2] is not None
    upper, mid, lower = bands[2]
    assert mid == 2.0  # (1+2+3)/3
    assert upper > mid > lower


def test_calculate_kd_stays_within_bounds() -> None:
    bars = [
        ConditionBar(date(2026, 1, i + 1), open=10, high=10 + i, low=9, close=9 + i, volume=100)
        for i in range(15)
    ]
    kd = calculate_kd(bars, period=9)
    assert len(kd) == len(bars)
    for k, d in kd:
        assert 0 <= k <= 100
        assert 0 <= d <= 100


def test_calculate_macd_returns_pairs_aligned_with_input() -> None:
    values = [float(i) for i in range(40)]
    macd = calculate_macd(values, short_period=12, long_period=26, signal_period=9)
    assert len(macd) == len(values)
    # 穩定上升的序列，長期下DIF應該收斂成正值
    dif, _signal = macd[-1]
    assert dif > 0


def test_resample_to_monthly_groups_by_year_month() -> None:
    bars = [
        ConditionBar(date(2026, 1, 5), open=10, high=12, low=9, close=11, volume=100),
        ConditionBar(date(2026, 1, 20), open=11, high=13, low=10, close=12, volume=200),
        ConditionBar(date(2026, 2, 3), open=12, high=12.5, low=11, close=12, volume=150),
    ]

    monthly = resample_to_monthly(bars)

    assert len(monthly) == 2
    assert monthly[0].open == 10  # 一月第一筆開盤
    assert monthly[0].close == 12  # 一月最後一筆收盤
    assert monthly[0].high == 13
    assert monthly[0].low == 9
    assert monthly[0].volume == 300
    assert monthly[1].trade_date == date(2026, 2, 3)
