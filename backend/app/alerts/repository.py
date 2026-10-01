from datetime import date, datetime, time

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.alerts.models import AlertLog
from app.rules.models import WatchRule


class AlertRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def list_alerts(
        self, limit: int, ticker: str | None = None, today_only: bool = False
    ) -> list[tuple[AlertLog, str]]:
        stmt = select(AlertLog, WatchRule.name).join(WatchRule, WatchRule.id == AlertLog.rule_id)

        if ticker:
            stmt = stmt.where(AlertLog.ticker == ticker)
        if today_only:
            today_start = datetime.combine(date.today(), time.min)
            stmt = stmt.where(AlertLog.triggered_at >= today_start)

        stmt = stmt.order_by(AlertLog.triggered_at.desc()).limit(limit)
        return list(self._db.execute(stmt).all())

    def exists_today(self, rule_id: int, ticker: str) -> bool:
        today_start = datetime.combine(date.today(), time.min)
        stmt = select(AlertLog.id).where(
            AlertLog.rule_id == rule_id,
            AlertLog.ticker == ticker,
            AlertLog.triggered_at >= today_start,
        )
        return self._db.scalars(stmt).first() is not None

    def create(self, alert: AlertLog) -> AlertLog:
        self._db.add(alert)
        self._db.commit()
        self._db.refresh(alert)
        return alert

    def exists_for_rule(self, rule_id: int) -> bool:
        stmt = select(AlertLog.id).where(AlertLog.rule_id == rule_id)
        return self._db.scalars(stmt).first() is not None

    def get_today(self, rule_id: int, ticker: str) -> AlertLog | None:
        today_start = datetime.combine(date.today(), time.min)
        return self._db.scalars(
            select(AlertLog)
            .where(
                AlertLog.rule_id == rule_id,
                AlertLog.ticker == ticker,
                AlertLog.triggered_at >= today_start,
            )
            .order_by(AlertLog.id.desc())
            .limit(1)
        ).first()

    def update_message(self, alert: AlertLog, message: str) -> None:
        alert.message = message
        self._db.commit()
