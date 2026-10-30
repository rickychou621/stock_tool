from datetime import datetime
from math import isfinite

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.alerts.repository import AlertRepository
from app.conditions.models import ConditionCatalog
from app.conditions.original_defaults import DEFAULT_PARAMS
from app.rules.models import WatchRule, WatchRuleCondition
from app.rules.repository import RuleRepository
from app.rules.schemas import WatchRuleCreateSchema, WatchRuleUpdateSchema


class RuleDeletionBlockedError(Exception):
    """規則已經有告警歷史，為了保留稽核紀錄不允許直接刪除，只能停用。"""


class RuleService:
    def __init__(self, db: Session) -> None:
        self._db = db
        self._repository = RuleRepository(db)
        self._alert_repository = AlertRepository(db)

    def list_rules(self, limit: int) -> list[WatchRule]:
        return self._repository.list_all(limit)

    def create_rule(self, payload: WatchRuleCreateSchema) -> WatchRule:
        rule = WatchRule(
            name=payload.name, logic_operator=payload.logic_operator, is_enabled=True,
            evaluation_frequency=payload.evaluation_frequency,
        )
        rule.conditions = [
            WatchRuleCondition(
                condition_id=c.condition_id,
                params={**DEFAULT_PARAMS.get(c.condition_id, {}), **c.params},
                sort_order=i, role=c.role
            )
            for i, c in enumerate(payload.conditions)
        ]
        return self._repository.create(rule)

    def delete_rule(self, rule_id: int) -> bool:
        if self._alert_repository.exists_for_rule(rule_id):
            raise RuleDeletionBlockedError(
                "這條規則已經有告警紀錄，為了保留歷史資料不能直接刪除，可以先停用。"
            )
        return self._repository.delete(rule_id)

    def set_enabled(self, rule_id: int, is_enabled: bool) -> WatchRule | None:
        return self._repository.set_enabled(rule_id, is_enabled)

    def update_rule(self, rule_id: int, payload: WatchRuleUpdateSchema) -> WatchRule | None:
        rule = self._repository.get(rule_id)
        if rule is None:
            return None
        conditions = sorted(rule.conditions, key=lambda c: c.sort_order)
        if [c.condition_id for c in conditions] != [c.condition_id for c in payload.conditions]:
            raise ValueError("條件組合不能在編輯時變更")
        catalogs = {c.id: c for c in self._db.scalars(
            select(ConditionCatalog).where(
                ConditionCatalog.id.in_([c.condition_id for c in conditions])
            )
        )}
        validated = []
        for incoming in payload.conditions:
            catalog = catalogs.get(incoming.condition_id)
            schema = catalog.param_schema if catalog else {}
            params = {}
            for key, value in incoming.params.items():
                error = f"條件 {incoming.condition_id} 的參數 {key}："
                if key not in schema:
                    raise ValueError(error + "不支援的參數")
                if value is None and schema[key] == "float":
                    continue
                if type(value) not in (int, float) or (
                    isinstance(value, float) and not isfinite(value)
                ):
                    raise ValueError(error + "必須是有限數字")
                if schema[key] == "int" and value != int(value):
                    raise ValueError(error + "必須是整數")
                minimum = 1 if key in {"period", "days", "slope_lookback"} or (
                    key.endswith("_period")
                ) else 0
                if value < minimum:
                    raise ValueError(error + f"必須大於或等於 {minimum}")
                params[key] = int(value) if schema[key] == "int" else value
            validated.append(params)
        for condition, params in zip(conditions, validated, strict=True):
            condition.params = params
        rule.name = payload.name
        rule.updated_at = datetime.utcnow()
        self._db.commit()
        self._db.refresh(rule)
        return rule
