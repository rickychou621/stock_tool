from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.rules.models import WatchRule


class RuleRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def list_all(self, limit: int) -> list[WatchRule]:
        stmt = (
            select(WatchRule)
            .options(selectinload(WatchRule.conditions))
            .order_by(WatchRule.id)
            .limit(limit)
        )
        return list(self._db.scalars(stmt))

    def get(self, rule_id: int) -> WatchRule | None:
        return self._db.get(WatchRule, rule_id)

    def list_enabled(self) -> list[WatchRule]:
        stmt = select(WatchRule).options(selectinload(WatchRule.conditions)).where(
            WatchRule.is_enabled.is_(True)
        )
        return list(self._db.scalars(stmt))

    def create(self, rule: WatchRule) -> WatchRule:
        self._db.add(rule)
        self._db.commit()
        self._db.refresh(rule)
        return rule

    def delete(self, rule_id: int) -> bool:
        rule = self.get(rule_id)
        if rule is None:
            return False
        self._db.delete(rule)
        self._db.commit()
        return True

    def set_enabled(self, rule_id: int, is_enabled: bool) -> WatchRule | None:
        rule = self.get(rule_id)
        if rule is None:
            return None
        rule.is_enabled = is_enabled
        self._db.commit()
        self._db.refresh(rule)
        return rule
