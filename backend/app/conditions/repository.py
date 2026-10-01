from sqlalchemy import select
from sqlalchemy.orm import Session

from app.conditions.models import ConditionCatalog


class ConditionRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def list_all(self) -> list[ConditionCatalog]:
        stmt = select(ConditionCatalog).order_by(ConditionCatalog.id)
        return list(self._db.scalars(stmt))
