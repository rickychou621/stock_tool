from dataclasses import asdict

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.alerts.notification import AlertNotificationService
from app.alerts.schemas import AlertMatchSchema, NotifyAlertsRequest, NotifyAlertsResponse
from app.alerts.service import AlertService
from app.core.dependencies import get_db

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("", response_model=list[AlertMatchSchema])
def list_alerts(
    limit: int = Query(10, ge=1, le=50),
    ticker: str | None = None,
    today_only: bool = False,
    db: Session = Depends(get_db),
) -> list[AlertMatchSchema]:
    service = AlertService(db)
    rows = service.get_alerts(limit, ticker=ticker, today_only=today_only)
    return [
        AlertMatchSchema(
            id=alert.id,
            ticker=alert.ticker,
            rule_name=rule_name,
            triggered_at=alert.triggered_at,
            price_at_trigger=(
                float(alert.price_at_trigger) if alert.price_at_trigger is not None else None
            ),
        )
        for alert, rule_name in rows
    ]


@router.post("/notify", response_model=NotifyAlertsResponse)
def notify_alerts(
    payload: NotifyAlertsRequest, db: Session = Depends(get_db)
) -> NotifyAlertsResponse:
    return NotifyAlertsResponse(**asdict(AlertNotificationService(db).notify(payload.alert_ids)))
