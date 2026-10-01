from sqlalchemy.orm import Session

from app.alerts.repository import AlertRepository
from app.rules.models import WatchRule, WatchRuleCondition
from app.rules.repository import RuleRepository
from app.rules.schemas import WatchRuleCreateSchema


class RuleDeletionBlockedError(Exception):
    """規則已經有告警歷史，為了保留稽核紀錄不允許直接刪除，只能停用。"""


class RuleService:
    def __init__(self, db: Session) -> None:
        self._repository = RuleRepository(db)
        self._alert_repository = AlertRepository(db)

    def list_rules(self, limit: int) -> list[WatchRule]:
        return self._repository.list_all(limit)

    def create_rule(self, payload: WatchRuleCreateSchema) -> WatchRule:
        rule = WatchRule(name=payload.name, logic_operator=payload.logic_operator, is_enabled=True)
        rule.conditions = [
            WatchRuleCondition(condition_id=c.condition_id, params=c.params, sort_order=i)
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
