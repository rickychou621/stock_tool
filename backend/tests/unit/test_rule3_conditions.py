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


@pytest.mark.parametrize("k,params,met,reason", [
    (69, {"max_k_at_cross": 70}, True, "KD 黃金交叉（K 69.0 > D 60.0，K ≤ 70 ✓）"),
    (70, {"max_k_at_cross": 70}, True, "KD 黃金交叉（K 70.0 > D 60.0，K ≤ 70 ✓）"),
    (71, {"max_k_at_cross": 70}, False, "KD 黃金交叉但 K=71.0 已在高檔（>70）"),
    (93, {}, True, "KD 黃金交叉（K 93.0 > D 60.0）"),
    (50.1, {"max_k_at_cross": 70}, False, "KD 未黃金交叉（K 50.1，D 60.0）"),
])
def test_golden_cross_optional_limit(monkeypatch, k, params, met, reason):
    monkeypatch.setattr("app.conditions.kd_macd.calculate_kd",
                        lambda *_: [(50, 60), (k, 60)])
    result = get_condition("kd_golden_cross")().evaluate(monthly([50] * 26), params)
    assert result.is_met is met
    assert result.reason == reason
    assert result.indicators == {"k": k, "d": 60, "crossed": float(k > 60)}


@pytest.mark.parametrize("dif,signal,met,reason", [
    (13.82, 2.77, True, "DIF 13.82 > 0 ✓｜MACD 2.77 > 0 ✓"),
    (-1.2, 2.77, False, "DIF -1.20 ≤ 0 ✗｜MACD 2.77 > 0 ✓"),
    (13.82, -1.2, False, "DIF 13.82 > 0 ✓｜MACD -1.20 ≤ 0 ✗"),
    (0, 0, False, "DIF 0.00 ≤ 0 ✗｜MACD 0.00 ≤ 0 ✗"),
])
def test_macd_positive_reason(monkeypatch, dif, signal, met, reason):
    monkeypatch.setattr("app.conditions.kd_macd.calculate_macd", lambda *_: [(dif, signal)])
    result = get_condition("macd_positive")().evaluate(monthly([50] * 26), {})
    assert result.is_met is met
    assert result.reason == reason


@pytest.mark.parametrize("k,signal,expected", [
    (69, 2.77, "ENTRY"), (71, 2.77, "HOLD"), (69, -1.2, "NONE"),
])
def test_strategy_three_entry_requires_positive_macd_and_k_limit(monkeypatch, k, signal, expected):
    from types import SimpleNamespace

    from app.rules.state import classify

    monkeypatch.setattr("app.conditions.kd_macd.calculate_kd",
                        lambda history, *_: [(50, 60), (k if len(history) == 27 else 50, 60)])
    monkeypatch.setattr("app.conditions.kd_macd.calculate_macd", lambda *_: [(13.82, signal)])
    rule = SimpleNamespace(
        id=2, logic_operator="AND", evaluation_frequency="daily",
        conditions=[
            SimpleNamespace(condition_id=cid, role=role, sort_order=i, params=params)
            for i, (cid, role, params) in enumerate([
                ("macd_positive", "premise", {}),
                ("kd_golden_cross", "entry", {"period": 9, "max_k_at_cross": 70}),
            ])
        ],
    )
    state = classify(rule, "TEST", monthly([50] * 27))
    assert state.state == expected
    if expected == "ENTRY":
        assert state.reason == (
            "KD 黃金交叉（K 69.0 > D 60.0，K ≤ 70 ✓）｜DIF 13.82 > 0 ✓｜MACD 2.77 > 0 ✓"
        )
    elif expected == "HOLD":
        assert state.reason == (
            "DIF 13.82 > 0 ✓｜MACD 2.77 > 0 ✓｜KD 黃金交叉但 K=71.0 已在高檔（>70）"
        )
    else:
        assert "MACD -1.20 ≤ 0 ✗" in state.reason


def test_insufficient_months_reports_counts_and_first_market_month():
    bars = [ConditionBar(date(2026, month, 1), 50, 50, 50, 50, 1000)
            for month in range(2, 10)]
    result = get_condition("macd_positive")().evaluate(bars, {"long_period": 35})
    assert result.reason == "月 K 資料不足：需要 35 根，目前 8 根（最早行情 2026/02）"
