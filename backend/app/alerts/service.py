from sqlalchemy.orm import Session

from app.alerts.models import AlertLog
from app.alerts.repository import AlertRepository


class AlertService:
    def __init__(self, db: Session) -> None:
        self._repository = AlertRepository(db)

    def get_alerts(
        self, limit: int, ticker: str | None = None, today_only: bool = False
    ) -> list[tuple[AlertLog, str]]:
        return self._repository.list_alerts(limit, ticker=ticker, today_only=today_only)
