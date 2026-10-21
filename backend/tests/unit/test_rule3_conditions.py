from datetime import date

import pytest

from app.conditions.registry import get_condition
from app.conditions.types import ConditionBar


def monthly(closes):
    return [
        ConditionBar(date(2020 + i // 12, i % 12 + 1, 1), c, max(100, c), 0, c, 1000)
        for i, c in enumerate(closes)
    ]


@pytest.mark.parametrize('previous, current, expected', [
    (70, 0, True), (69.9, 0, False), (70, 100, False),
])
def test_high_death_cross_threshold(previous, current, expected):
    # RSV 80, 90 puts K at 60, 70; flat RSV 70 then keeps K exactly 70.
    bars = monthly([80, 90] + [70] * 6 + [3 * previous - 140, current])
    result = get_condition('kd_high_death_cross')().evaluate(bars, {})
    assert result.is_met is expected
    assert result.indicators['prev_k'] == pytest.approx(previous)
    assert set(result.indicators) == {'k', 'd', 'prev_k'}
    assert '高檔死亡交叉' in result.reason


@pytest.mark.parametrize('cid, count', [('kd_high_death_cross', 9), ('macd_negative_any', 25)])
def test_insufficient_months(cid, count):
    result = get_condition(cid)().evaluate(monthly([50] * count), {})
    assert not result.is_met
    assert not result.data_sufficient


@pytest.mark.parametrize('closes, dif_negative, signal_negative', [
    ([80 - i for i in range(26)], True, True),
    ([50 + i for i in range(25)] + [0], True, False),
    ([80 - i for i in range(25)] + [130], False, True),
    ([20 + i for i in range(26)], False, False),
    ([50] * 26, False, False),
])
def test_macd_negative_either_line(closes, dif_negative, signal_negative):
    result = get_condition('macd_negative_any')().evaluate(monthly(closes), {})
    assert (result.indicators['dif'] < 0) is dif_negative
    assert (result.indicators['signal'] < 0) is signal_negative
    assert result.is_met is (dif_negative or signal_negative)
    assert result.data_sufficient
    assert f"DIF={result.indicators['dif']:.2f}" in result.reason
    assert f"MACD訊號線={result.indicators['signal']:.2f}" in result.reason


def test_high_death_cross_requires_a_new_cross_not_an_existing_death_cross():
    result = get_condition('kd_high_death_cross')().evaluate(monthly([100] * 9 + [70, 65]), {})
    assert result.indicators['prev_k'] > 70
    assert result.indicators['k'] < result.indicators['d']
    assert not result.is_met


def test_high_death_cross_custom_period_and_threshold():
    condition = get_condition('kd_high_death_cross')()
    bars = monthly([80, 90, 70, 0])
    assert not condition.evaluate(bars, {}).data_sufficient
    assert condition.evaluate(bars, {'period': 3, 'threshold': 70}).is_met
    assert not condition.evaluate(bars, {'period': 3, 'threshold': 71}).is_met


def test_macd_negative_custom_periods():
    result = get_condition('macd_negative_any')().evaluate(
        monthly([80, 70, 60]), {'short_period': 2, 'long_period': 3, 'signal_period': 2}
    )
    assert result.data_sufficient
    assert result.is_met
