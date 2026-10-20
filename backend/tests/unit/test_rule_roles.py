from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.backtest.service import restore_rule, rule_snapshot
from app.rules.evaluation import RuleEvaluationService
from app.rules.models import WatchRule, WatchRuleCondition
from app.rules.schemas import WatchRuleConditionSchema, WatchRuleCreateSchema


def condition(met=True, role=None, sufficient=True, unknown=False):
    fields = dict(
        condition_id="unknown" if unknown else "stub",
        params=dict(is_met=met, data_sufficient=sufficient),
        sort_order=0,
    )
    if role is not None:
        fields["role"] = role
    return SimpleNamespace(**fields)


def rule(conditions, operator="AND"):
    return SimpleNamespace(id=1, name="test", logic_operator=operator, conditions=conditions)


@pytest.fixture(autouse=True)
def condition_registry(monkeypatch):
    class Stub:
        def evaluate(self, bars, params):
            return SimpleNamespace(
                **params, reason="condition reason", upper_band_status=None, indicators={}
            )

    def lookup(name):
        if name == "unknown":
            raise KeyError(name)
        return Stub

    monkeypatch.setattr("app.rules.evaluation.get_condition", lookup)


def evaluate(conditions, operator="AND"):
    return RuleEvaluationService.evaluate_bars(rule(conditions, operator), "TEST", [])


@pytest.mark.parametrize("operator", ["AND", "OR"])
@pytest.mark.parametrize("values", [(True, True), (True, False), (False, False)])
@pytest.mark.parametrize("sufficient", [True, False])
def test_legacy_premises_preserve_results(operator, values, sufficient):
    result = evaluate([condition(met=v, sufficient=sufficient) for v in values], operator)
    expected = any(values) if operator == "OR" else all(values)
    status = "matched" if expected else ("not_met" if sufficient else "insufficient_data")
    assert (result.is_met, result.premise_met, result.status) == (expected, expected, status)
    assert result.entry_triggered is None and result.exit_triggered is None
    assert [(c.is_met, c.reason, c.role) for c in result.condition_results] == [
        (v, "condition reason", "premise") for v in values
    ]


@pytest.mark.parametrize("operator,premise", [("AND", False), ("OR", True)])
@pytest.mark.parametrize("entry_values", [(True, True), (True, False), (False, False)])
@pytest.mark.parametrize("exit_values", [(True, True), (True, False), (False, False)])
def test_roles_combine_independently(operator, premise, entry_values, exit_values):
    result = evaluate(
        [condition(True, "premise"), condition(False, "premise")]
        + [condition(v, "entry") for v in entry_values]
        + [condition(v, "exit") for v in exit_values],
        operator,
    )
    assert result.is_met == result.premise_met == premise
    assert result.entry_triggered == all(entry_values)
    assert result.exit_triggered == any(exit_values)
    assert result.status == ("matched" if premise else "not_met")
    assert [c.role for c in result.condition_results] == [
        "premise", "premise", "entry", "entry", "exit", "exit"
    ]


@pytest.mark.parametrize("met", [True, False])
def test_trigger_insufficient_data_does_not_change_premise_status(met):
    result = evaluate([
        condition(met), condition(False, "entry", sufficient=False),
        condition(False, "exit", sufficient=False),
    ])
    assert result.status == ("matched" if met else "not_met")


@pytest.mark.parametrize("role", ["premise", "entry", "exit"])
def test_missing_implementation_is_error_for_every_role(role):
    result = evaluate([condition(True), condition(role=role, unknown=True)], "OR")
    assert result.status == "error"
    assert result.is_met is result.premise_met is False
    assert result.condition_results[-1].reason == "找不到這個條件的實作"
    assert result.condition_results[-1].role == role


@pytest.mark.parametrize("conditions", [[], [condition(True, "entry"), condition(True, "exit")]])
def test_missing_premise_is_error(conditions):
    result = evaluate(conditions)
    assert result.status == "error" and not result.is_met and not result.premise_met
    assert result.condition_results[-1].reason == "戰法缺少前提條件"


def test_default_and_invalid_roles():
    assert WatchRuleConditionSchema(condition_id="stub", params={}).role == "premise"
    with pytest.raises(ValidationError):
        WatchRuleConditionSchema(condition_id="stub", params={}, role="invalid")
    with pytest.raises(ValueError):
        WatchRuleCondition(condition_id="stub", role="invalid")
    with pytest.raises(ValidationError, match="戰法缺少前提條件"):
        WatchRuleCreateSchema(name="test", logic_operator="AND", conditions=[])
    engine = create_engine("sqlite://")
    WatchRule.__table__.create(engine)
    WatchRuleCondition.__table__.create(engine)
    with Session(engine) as db:
        item = WatchRuleCondition(condition_id="stub", rule_id=1)
        db.add(item)
        db.flush()
        assert item.role == "premise"
    engine.dispose()


def test_snapshot_roundtrip_and_legacy_restore():
    original = rule([condition(True), condition(True, "entry"), condition(False, "exit")])
    snapshot = rule_snapshot(original)
    assert [c["role"] for c in snapshot["conditions"]] == ["premise", "entry", "exit"]
    result = RuleEvaluationService.evaluate_bars(restore_rule(snapshot), "TEST", [])
    assert result.is_met and result.entry_triggered and not result.exit_triggered
    legacy = rule_snapshot(rule([condition(True)]))
    del legacy["conditions"][0]["role"]
    restored = restore_rule(legacy)
    assert restored.conditions[0].role == "premise"
    result = RuleEvaluationService.evaluate_bars(restored, "TEST", [])
    assert result.is_met and result.status == "matched"
    assert result.entry_triggered is result.exit_triggered is None
    assert "role" not in legacy["conditions"][0]


def test_evaluation_api_serializes_role_fields(monkeypatch):
    from app.rules.router import evaluate_rule

    strategy = rule([condition(True), condition(False, "entry"), condition(True, "exit")])
    monkeypatch.setattr("app.rules.router.RuleRepository.get", lambda self, rule_id: strategy)
    monkeypatch.setattr(
        "app.rules.router.RuleEvaluationService.evaluate",
        lambda self, rule, ticker: RuleEvaluationService.evaluate_bars(rule, ticker, []),
    )
    payload = evaluate_rule(1, "TEST", None).model_dump(by_alias=True)
    assert payload["isMet"] is payload["premiseMet"] is True
    assert payload["entryTriggered"] is False
    assert payload["exitTriggered"] is True
    assert [c["role"] for c in payload["conditionResults"]] == ["premise", "entry", "exit"]
