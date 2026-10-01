from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.dependencies import get_db
from app.rules.evaluation import RuleEvaluationService
from app.rules.models import WatchRule
from app.rules.preparation import EvaluationPreparationService, PreparationError
from app.rules.repository import RuleRepository
from app.rules.schemas import (
    ConditionEvaluationSchema,
    RuleEvaluationSchema,
    WatchRuleConditionSchema,
    WatchRuleCreateSchema,
    WatchRuleSchema,
)
from app.rules.service import RuleDeletionBlockedError, RuleService

router = APIRouter(prefix="/rules", tags=["rules"])


def _to_schema(rule: WatchRule) -> WatchRuleSchema:
    return WatchRuleSchema(
        id=rule.id,
        name=rule.name,
        logic_operator=rule.logic_operator,
        is_enabled=rule.is_enabled,
        conditions=[
            WatchRuleConditionSchema(condition_id=c.condition_id, params=c.params)
            for c in sorted(rule.conditions, key=lambda c: c.sort_order)
        ],
    )


@router.get("", response_model=list[WatchRuleSchema])
def list_rules(
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
) -> list[WatchRuleSchema]:
    service = RuleService(db)
    return [_to_schema(rule) for rule in service.list_rules(limit)]


@router.post("", response_model=WatchRuleSchema, status_code=201)
def create_rule(payload: WatchRuleCreateSchema, db: Session = Depends(get_db)) -> WatchRuleSchema:
    service = RuleService(db)
    return _to_schema(service.create_rule(payload))


@router.patch("/{rule_id}/enabled", response_model=WatchRuleSchema)
def set_rule_enabled(
    rule_id: int,
    is_enabled: bool,
    db: Session = Depends(get_db),
) -> WatchRuleSchema:
    service = RuleService(db)
    rule = service.set_enabled(rule_id, is_enabled)
    if rule is None:
        raise HTTPException(status_code=404, detail="Rule not found")
    return _to_schema(rule)


@router.delete("/{rule_id}", status_code=204)
def delete_rule(rule_id: int, db: Session = Depends(get_db)) -> None:
    service = RuleService(db)
    try:
        if not service.delete_rule(rule_id):
            raise HTTPException(status_code=404, detail="Rule not found")
    except RuleDeletionBlockedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/{rule_id}/evaluate", response_model=RuleEvaluationSchema)
def evaluate_rule(
    rule_id: int,
    ticker: str,
    db: Session = Depends(get_db),
) -> RuleEvaluationSchema:
    """對外的「算現在符不符合」接口。排程之後要跑同一套判斷時，
    直接呼叫 RuleEvaluationService(db).evaluate(rule, ticker) 就好，不用重寫邏輯。"""
    rule = RuleRepository(db).get(rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Rule not found")

    result = RuleEvaluationService(db).evaluate(rule, ticker)
    return RuleEvaluationSchema(
        rule_id=result.rule_id,
        ticker=result.ticker,
        is_met=result.is_met,
        logic_operator=result.logic_operator,
        status=result.status,
        data_date=result.data_date,
        condition_results=[
            ConditionEvaluationSchema(
                condition_id=c.condition_id,
                is_met=c.is_met,
                reason=c.reason,
                data_sufficient=c.data_sufficient,
            )
            for c in result.condition_results
        ],
    )


@router.post("/{rule_id}/prepare")
def prepare_evaluation(
    rule_id: int,
    ticker: str,
    db: Session = Depends(get_db),
) -> dict:
    rule = RuleRepository(db).get(rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="找不到規則")
    try:
        rows = EvaluationPreparationService(db).prepare(rule, ticker)
    except PreparationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail="行情更新失敗，請稍後重試；本次未評估。"
        ) from exc
    return {"ticker": ticker, "rowsSynced": rows}
