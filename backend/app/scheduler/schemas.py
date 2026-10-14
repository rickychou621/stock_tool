from datetime import date, datetime

from pydantic import Field

from app.core.schemas import CamelModel


class ScheduleSettingsSchema(CamelModel):
    enabled: bool = True
    rule_ids: list[int] = Field(default_factory=list, max_length=50)


class ScheduleErrorSchema(CamelModel):
    id: int
    batch_id: str
    ticker: str | None
    occurred_at: datetime
    reason: str


class ScheduleRunSchema(CamelModel):
    batch_id: str
    trade_date: date
    started_at: datetime
    finished_at: datetime | None
    status: str
    total: int
    succeeded: int
    failed: int
    errors: list[ScheduleErrorSchema]
