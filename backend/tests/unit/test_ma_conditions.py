import re
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

import pytest

from app.conditions.base import UpdateFrequency
from app.conditions.moving_average import (
    CloseBelowMaDaysCondition,
    MaRisingCondition,
    MaTouchReboundCondition,
    PriceTouchMaCondition,
)
from app.conditions.registry import get_condition
from app.conditions.types import ConditionBar


def _bars(closes: list[float]) -> list[ConditionBar]:
    return [
        ConditionBar(date(2026, 1, 1) + timedelta(days=i), close, close, close, close, 1000)
        for i, close in enumerate(closes)
    ]


@pytest.mark.parametrize(
    ("closes", "expected", "ma", "ma_prev"),
    [
        ([100.0] * 25, False, 100.0, 100.0),
        ([100.0] * 24 + [120.0], True, 101.0, 100.0),
        ([100.0] * 24 + [80.0], False, 99.0, 100.0),
    ],
)
def test_ma_rising_defaults(closes, expected, ma, ma_prev):
    result = MaRisingCondition().evaluate(_bars(closes), {})
    assert result.data_sufficient
    assert result.is_met is expected
    assert result.indicators == {"ma": ma, "ma_prev": ma_prev, "slope": ma - ma_prev,
                                 "slope_pct": ma / ma_prev - 1}
    assert f"{ma:.2f}" in result.reason
    assert "5 日前" in result.reason


def test_ma_rising_custom_window():
    result = MaRisingCondition().evaluate(
        _bars([900.0, 10.0, 10.0, 20.0, 20.0]), {"period": "2", "slope_lookback": "2"}
    )
    assert result.is_met
    assert result.indicators == {"ma": 20.0, "ma_prev": 10.0, "slope": 10.0, "slope_pct": 1.0}


@pytest.mark.parametrize(
    ("condition", "params", "required"),
    [
        (MaRisingCondition, {}, 25),
        (MaRisingCondition, {"period": 3, "slope_lookback": 2}, 5),
        (PriceTouchMaCondition, {}, 20),
        (PriceTouchMaCondition, {"period": 2}, 2),
        (CloseBelowMaDaysCondition, {}, 21),
        (CloseBelowMaDaysCondition, {"period": 3, "days": 3}, 5),
    ],
)
def test_data_sufficiency_boundary(condition, params, required):
    for count in (0, required - 1):
        result = condition().evaluate(_bars([100.0] * count), params)
        assert result.is_met is False
        assert result.data_sufficient is False
        assert result.reason == "資料不足，無法判斷"
        assert result.indicators == {}
    assert condition().evaluate(_bars([100.0] * required), params).data_sufficient


@pytest.mark.parametrize(
    ("low", "close", "params", "expected"),
    [
        (101.0, 102.0, {}, True),
        (101.00001, 102.0, {}, False),
        (99.0, 100.0, {}, True),
        (98.0, 99.0, {}, False),
        (101.5, 102.0, {}, False),
        (101.5, 102.0, {"tolerance": "0.02"}, True),
        (100.0, 102.0, {"tolerance": 0}, True),
        (100.001, 102.0, {"tolerance": 0}, False),
    ],
)
def test_price_touch_boundaries(low, close, params, expected):
    # 保持20日均價恰好100，並維持 low <= close。
    bars = _bars([100.0] * 18 + [200.0 - close, close])
    bars[-1] = replace(bars[-1], low=low)
    result = PriceTouchMaCondition().evaluate(bars, params)
    assert result.is_met is expected
    assert result.indicators == {
        "ma": 100.0, "low": low, "close": close, "distance": low / 100.0 - 1,
    }
    for value in (low, close, 100.0):
        assert f"{value:.2f}" in result.reason


@pytest.mark.parametrize(
    ("closes", "days", "expected", "below_days", "ma"),
    [
        ([10.0, 10.0, 9.0, 8.0], 2, True, 2, 9.0),
        ([10.0, 10.0, 10.0, 9.0], 2, False, 1, 29 / 3),
        ([10.0, 10.0, 9.0, 11.0, 8.0], 3, False, 1, 28 / 3),
        ([10.0, 10.0, 8.0, 9.0], 2, False, 0, 9.0),
        ([10.0, 10.0, 9.0, 8.0, 7.0], 3, True, 3, 8.0),
        ([10.0, 10.0, 9.0, 8.0, 7.0], 2, True, 2, 8.0),
        ([10.0, 10.0, 9.0], 1, True, 1, 29 / 3),
    ],
)
def test_close_below_uses_each_days_own_ma(closes, days, expected, below_days, ma):
    result = CloseBelowMaDaysCondition().evaluate(
        _bars(closes), {"period": "3", "days": str(days)}
    )
    assert result.data_sufficient
    assert result.is_met is expected
    assert result.indicators == {"ma": ma, "close": closes[-1], "below_days": below_days,
                                 "buffer": 0}
    assert f"連續 {below_days} 天" in result.reason


def test_close_below_defaults():
    result = CloseBelowMaDaysCondition().evaluate(_bars([100.0] * 19 + [99.0, 98.0]), {})
    assert result.is_met
    assert result.indicators == {"ma": 99.85, "close": 98.0, "below_days": 2, "buffer": 0}


def test_catalog_ids_match_registered_daily_conditions():
    conditions = (MaRisingCondition, PriceTouchMaCondition, CloseBelowMaDaysCondition)
    migration = Path(__file__).resolve().parents[3] / "mysql/init/015_ma_conditions.sql"
    sql = migration.read_text()
    ids = set(re.findall(r"^\s+\('([^']+)',", sql, re.MULTILINE))
    assert ids == {condition.id for condition in conditions}
    for condition in conditions:
        assert get_condition(condition.id) is condition
        assert condition.required_timeframe == "日K"
        assert condition.update_frequency == UpdateFrequency.DAILY


@pytest.mark.parametrize("closes", [[100] * 25, [100] * 24 + [120], [100] * 24 + [80]])
def test_explicit_defaults_preserve_results(closes):
    bars = _bars(closes)
    assert MaRisingCondition().evaluate(bars, {}) == MaRisingCondition().evaluate(
        bars, {"min_slope_pct": None})
    assert CloseBelowMaDaysCondition().evaluate(bars, {}) == CloseBelowMaDaysCondition().evaluate(
        bars, {"buffer": 0})


@pytest.mark.parametrize("last,expected", [(119.999, False), (120, True), (120.001, True)])
def test_min_slope_boundary(last, expected):
    result = MaRisingCondition().evaluate(_bars([100] * 24 + [last]), {"min_slope_pct": 0.01})
    assert result.is_met is expected
    assert result.indicators["slope_pct"] == pytest.approx((last - 100) / 2000)


@pytest.mark.parametrize("last,expected", [(97.999, True), (98, False), (98.001, False)])
def test_exit_buffer_strict_boundary(last, expected):
    result = CloseBelowMaDaysCondition().evaluate(
        _bars([102, last]), {"period": 2, "days": 1, "buffer": 0.02})
    assert result.is_met is expected
    assert result.indicators["buffer"] == 0.02
    assert "月線下方 2%" in result.reason


def test_buffer_requires_each_days_own_ma_and_consecutive_days():
    condition = CloseBelowMaDaysCondition()
    assert condition.evaluate(_bars([110, 100, 90]),
                              {"period": 2, "days": 2, "buffer": 0.02}).is_met
    assert not condition.evaluate(_bars([100, 100, 90]),
                                  {"period": 2, "days": 2, "buffer": 0.02}).is_met


@pytest.mark.parametrize("closes,low,expected", [
    ([100, 100, 102], 100, True),
    ([100, 104, 106], 104, False),  # previous low above its own MA tolerance
    ([104, 100, 102], 99, False),  # previous close below its MA
    ([100, 100, 100], 100, False),
    ([100, 100, 99], 100, False),
])
def test_rebound(closes, low, expected):
    bars = _bars(closes)
    bars[-2] = replace(bars[-2], low=low)
    result = MaTouchReboundCondition().evaluate(bars, {"period": 2})
    assert result.is_met is expected
    assert result.indicators == {"ma": sum(closes[-2:]) / 2,
                                 "prev_ma": sum(closes[:2]) / 2,
                                 "close": closes[-1], "prev_close": closes[-2]}


def test_rebound_today_below_ma_despite_rising_close():
    # Dropping a low old bar raises today's MA above the rebound close.
    bars = _bars([0, 200, 100, 101])
    assert not MaTouchReboundCondition().evaluate(bars, {"period": 3}).is_met


@pytest.mark.parametrize("count", [0, 19, 20])
def test_rebound_insufficient_data(count):
    result = MaTouchReboundCondition().evaluate(_bars([100] * count), {})
    assert not result.is_met and not result.data_sufficient


def test_rebound_catalog_is_additive_repeatable_and_registered():
    sql = (Path(__file__).resolve().parents[3] / "mysql/init/019_ma_touch_rebound.sql").read_text()
    assert "ON DUPLICATE KEY UPDATE" in sql
    assert set(re.findall(r"^\s+\('([^']+)',", sql, re.MULTILINE)) == {"ma_touch_rebound"}
    assert "watch_rule" not in sql and "DELETE" not in sql
    assert get_condition("ma_touch_rebound") is MaTouchReboundCondition
