from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.conditions.moving_average import CloseBelowMaDaysCondition
from app.conditions.types import ConditionBar
from app.core.config import Settings
from app.rules.evaluation import RuleEvaluationService
from app.rules.state import (
    ENTRY,
    EXIT,
    HOLD,
    NEAR_EXIT,
    NO_DATA,
    NONE,
    STALE,
    STATE_LABELS,
    STATES,
    URGENCY,
    classify,
)


def condition(role="premise", met=True, **params):
    return SimpleNamespace(
        condition_id="stub", role=role, sort_order=0,
        params=dict(met=met, reason=f"{role} reason", **params),
    )


def rule(*conditions, frequency="daily"):
    return SimpleNamespace(
        id=1, logic_operator="AND", conditions=list(conditions), evaluation_frequency=frequency,
    )


def bars(count=3):
    return [ConditionBar(date(2026, 10, 1) + timedelta(days=i), 100, 100, 100, 100, 1000)
            for i in range(count)]


@pytest.fixture(autouse=True)
def registry(monkeypatch):
    calls = []

    class Stub:
        def evaluate(self, history, params):
            calls.append(history[-1].trade_date)
            met = params["met"]
            sufficient = params.get("sufficient", True)
            return SimpleNamespace(
                is_met=met(history) if callable(met) else met,
                reason=params["reason"], upper_band_status=None, indicators={},
                data_sufficient=sufficient(history) if callable(sufficient) else sufficient,
            )

    def lookup(name):
        if name == "close_below_ma_days":
            return CloseBelowMaDaysCondition
        if name == "unknown":
            raise KeyError(name)
        return Stub

    monkeypatch.setattr("app.rules.evaluation.get_condition", lookup)
    return calls


def test_state_catalog_includes_stale_without_classifying_it():
    assert STATES == (ENTRY, HOLD, NEAR_EXIT, EXIT, NONE, NO_DATA, STALE)
    assert STATE_LABELS == {
        ENTRY: "進場", HOLD: "續抱", NEAR_EXIT: "接近出場", EXIT: "出場",
        NONE: "不符合", NO_DATA: "資料不足", STALE: "需重新評估",
    }
    assert sorted(STATES, key=URGENCY.get) == [EXIT, NEAR_EXIT, ENTRY, HOLD, STALE, NO_DATA, NONE]


@pytest.mark.parametrize("with_entry", [False, True])
def test_entry_then_hold(with_entry):
    def trigger(history):
        return len(history) >= 2

    strategy = (rule(condition(), condition("entry", trigger)) if with_entry
                else rule(condition(met=trigger)))
    entered = classify(strategy, "TEST", bars(2))
    assert entered.state == ENTRY
    assert entered.reason == ("entry reason｜premise reason" if with_entry else "premise reason")
    held = classify(strategy, "TEST", bars(3))
    assert (held.state, held.reason) == (HOLD, "premise reason")
    assert (held.trigger_price, held.close, held.distance_pct) == (None, None, None)


def test_exit_precedes_entry_and_joins_only_met_exit_reasons(registry):
    strategy = rule(condition(), condition("entry"), condition("exit"), condition("exit", False))
    state = classify(strategy, "TEST", bars(1))
    assert (state.state, state.reason) == (EXIT, "exit reason")
    assert len(registry) == 4


def test_none_uses_first_failed_premise_and_skips_previous(registry):
    strategy = rule(condition(met=False), condition(met=False), condition("entry"))
    state = classify(strategy, "TEST", bars())
    assert (state.state, state.reason) == (NONE, "premise reason")
    assert len(registry) == 3


def test_supplied_result_is_reused_and_false_entry_skips_previous(registry):
    strategy = rule(condition(), condition("entry", False))
    result = RuleEvaluationService.evaluate_bars(strategy, "TEST", bars())
    registry.clear()
    assert classify(strategy, "TEST", bars(), result).state == HOLD
    assert registry == []


def test_empty_bars_does_not_evaluate(registry):
    assert classify(rule(condition()), "TEST", []).state == NO_DATA
    assert registry == []


@pytest.mark.parametrize("error", [False, True])
def test_current_invalid_result(error):
    item = condition(met=False, sufficient=False)
    if error:
        item.condition_id = "unknown"
    state = classify(rule(item, condition("exit")), "TEST", bars())
    assert state.state == NO_DATA
    assert state.reason == ("找不到這個條件的實作" if error else "premise reason")


@pytest.mark.parametrize("role", ["premise", "entry", "exit"])
def test_previous_insufficient_any_role(role):
    item = condition(role, sufficient=lambda history: len(history) >= 3)
    strategy = rule(condition(), item)
    if role == "exit":
        item.params["met"] = False
    state = classify(strategy, "TEST", bars())
    assert (state.state, state.reason) == (NO_DATA, f"前一個有效交易日資料不足：{role} reason")


@pytest.mark.parametrize("status", ["error", "insufficient_data"])
def test_previous_invalid_status(status):
    strategy = rule(condition())
    current = RuleEvaluationService.evaluate_bars(strategy, "TEST", bars())
    strategy.conditions[0].params["met"] = False
    if status == "error":
        strategy.conditions[0].condition_id = "unknown"
    else:
        strategy.conditions[0].params["sufficient"] = False
    state = classify(strategy, "TEST", bars(), current)
    assert state.state == NO_DATA
    assert state.reason.startswith("前一個有效交易日資料不足：")


@pytest.mark.parametrize("frequency,count", [("daily", 1), ("weekly", 1), ("weekly", 2)])
def test_missing_previous_day(frequency, count):
    state = classify(rule(condition(), frequency=frequency), "TEST", bars(count))
    assert state.state == NO_DATA
    assert state.reason.startswith("前一個有效交易日資料不足：")


def test_weekly_uses_previous_friday(registry):
    history = [b for b in bars(9) if b.trade_date.weekday() < 5]
    strategy = rule(condition(met=lambda h: h[-1].trade_date > date(2026, 10, 2)),
                    frequency="weekly")
    assert classify(strategy, "TEST", history).state == ENTRY
    assert registry == [date(2026, 10, 9), date(2026, 10, 2)]


def stop_rule():
    exit_condition = SimpleNamespace(
        condition_id="close_below_ma_days", role="exit", sort_order=1,
        params={"period": 20, "days": 2, "buffer": 0.02},
    )
    return rule(condition(), condition("entry", False), exit_condition)


@pytest.mark.parametrize("kind,price,distance", [("stock", 97.7, 2.4), ("etf", 97.85, 2.2)])
def test_real_buffered_stop_distance(kind, price, distance):
    state = classify(stop_rule(), "TEST", bars(22), kind=kind)
    assert state.state == NEAR_EXIT
    assert (state.trigger_price, state.close, state.distance_pct) == (price, 100, distance)
    assert state.reason == f"收盤距觸價 {distance:.1f}%"


def test_threshold_override_and_settings(monkeypatch):
    strategy, history = stop_rule(), bars(22)
    monkeypatch.setattr("app.rules.state.get_settings", lambda: SimpleNamespace(near_exit_pct=0.01))
    assert classify(strategy, "TEST", history).state == HOLD
    assert classify(strategy, "TEST", history, near_exit_pct=0.03).state == NEAR_EXIT
    assert classify(strategy, "TEST", history, near_exit_pct=0.02).state == HOLD


def test_below_stop_is_near_exit_before_consecutive_exit():
    history = bars(22)
    history[-1] = ConditionBar(history[-1].trade_date, 96, 96, 96, 96, 1000)
    state = classify(stop_rule(), "TEST", history)
    assert state.state == NEAR_EXIT
    assert state.distance_pct < 0


def test_missing_close_does_not_calculate_distance():
    strategy, history = stop_rule(), bars(22)
    result = RuleEvaluationService.evaluate_bars(strategy, "TEST", history)
    del result.condition_results[-1].indicators["close"]
    state = classify(strategy, "TEST", history, result)
    assert state.state == HOLD
    assert state.trigger_price == 97.7
    assert state.close is state.distance_pct is None


@pytest.mark.parametrize("value", [0, 1, -0.1, float("inf"), float("nan")])
def test_settings_reject_invalid_threshold(value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, near_exit_pct=value)


@pytest.mark.parametrize("indicators", [
    ({"close_distance_pct": 0.0324}, {"slope_pct": 0.00356}, 3.2, 0.36),
    ({"close_distance_pct": -0.0124}, {"slope_pct": -0.00356}, -1.2, -0.36),
    ({"close_distance_pct": 0}, {"slope_pct": 0}, 0, 0),
    ({}, {}, None, None),
])
def test_strategy_two_ma_indicators(indicators):
    distance, slope, expected_distance, expected_slope = indicators
    strategy = stop_rule()
    result = RuleEvaluationService.evaluate_bars(strategy, "TEST", bars(22))
    result.condition_results[0].condition_id = "ma_rising"
    result.condition_results[0].indicators = slope
    result.condition_results[1].condition_id = "ma_touch_rebound"
    result.condition_results[1].indicators = distance

    state = classify(strategy, "TEST", bars(22), result)
    assert state.ma_distance_pct == expected_distance
    assert state.ma_slope_pct == expected_slope


def test_strategy_three_has_no_ma_indicators():
    strategy = rule(
        condition(), condition("entry", False), condition("exit", False), condition("exit", False),
        frequency="weekly",
    )
    for item, condition_id in zip(strategy.conditions, (
        "macd_positive", "kd_golden_cross", "kd_high_death_cross", "macd_negative_any",
    ), strict=True):
        item.condition_id = condition_id

    state = classify(strategy, "TEST", bars())
    assert state.ma_distance_pct is None
    assert state.ma_slope_pct is None


def test_entry_reason_includes_all_premises_for_or_rule():
    strategy = rule(
        condition(met=True), condition(met=False),
        condition("entry", lambda history: len(history) >= 3),
        condition("entry", True),
    )
    strategy.logic_operator = "OR"
    state = classify(strategy, "TEST", bars())
    assert state.state == ENTRY
    assert state.reason == "entry reason｜entry reason｜premise reason｜premise reason"


def test_hold_reason_includes_only_failed_entries_after_all_premises():
    strategy = rule(
        condition(), condition(), condition("entry", True), condition("entry", False),
    )
    state = classify(strategy, "TEST", bars())
    assert (state.state, state.reason) == (HOLD, "premise reason｜premise reason｜entry reason")


@pytest.mark.parametrize("sufficient", [False, True])
def test_missing_reasons_are_unique_in_original_order(sufficient):
    from app.rules.state import _missing_reason

    result = SimpleNamespace(condition_results=[
        SimpleNamespace(reason=reason, data_sufficient=sufficient, is_met=False)
        for reason in ("原因甲", "原因甲", "原因乙", "原因甲")
    ])
    assert _missing_reason(result) == "原因甲；原因乙"


def test_missing_reason_keeps_largest_requirement_per_timeframe():
    from app.rules.state import _missing_reason

    reasons = (
        "月 K 資料不足：需要 26 根，目前 7 根",
        "月 K 資料不足：需要 10 根，目前 7 根",
        "日 K 資料不足：需要 25 根，目前 7 根",
        "月 K 資料不足：需要 10 根，目前 7 根",
    )
    result = SimpleNamespace(condition_results=[
        SimpleNamespace(reason=reason, data_sufficient=False, is_met=False) for reason in reasons
    ])
    assert _missing_reason(result) == (
        "月 K 資料不足：需要 26 根，目前 7 根；日 K 資料不足：需要 25 根，目前 7 根"
    )
