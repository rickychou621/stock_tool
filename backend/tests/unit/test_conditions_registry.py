from app.conditions.base import Condition, ConditionResult, UpdateFrequency
from app.conditions.registry import get_condition, list_conditions, register_condition


@register_condition
class _DummyCondition(Condition):
    id = "dummy"
    name = "Dummy"
    required_timeframe = "daily"
    update_frequency = UpdateFrequency.DAILY

    def evaluate(self, data: object, params: dict) -> ConditionResult:
        return ConditionResult(is_met=True, reason="always true")


def test_register_and_retrieve_condition() -> None:
    assert get_condition("dummy") is _DummyCondition
    assert _DummyCondition in list_conditions()


def test_condition_evaluate() -> None:
    result = _DummyCondition().evaluate(data=None, params={})
    assert result.is_met is True
    assert result.reason == "always true"


def test_registered_condition_text_has_no_mojibake() -> None:
    conditions = list_conditions()
    assert any(condition.id == "macd_histogram_rising" for condition in conditions)
    for condition in conditions:
        for field in ("required_timeframe", "name", "description"):
            text = getattr(condition, field, "")
            assert not any(marker in text for marker in ("æ", "Ã", "â€")), (
                condition.id, field, text
            )
