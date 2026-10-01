"""告警對外API的請求/回應格式。"""

from datetime import datetime

from pydantic import Field

from app.core.schemas import CamelModel


class AlertMatchSchema(CamelModel):
    id: int
    ticker: str
    rule_name: str
    triggered_at: datetime
    price_at_trigger: float | None


class NotifyAlertsRequest(CamelModel):
    alert_ids: list[int] = Field(min_length=1, max_length=500)


class NotifyAlertsResponse(CamelModel):
    sent_ids: list[int]
    skipped_ids: list[int]
    failed_ids: list[int]
