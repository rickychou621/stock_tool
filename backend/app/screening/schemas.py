"""候選池對外API的請求/回應格式。"""

from datetime import date, datetime
from typing import Literal

from app.core.schemas import CamelModel


class CandidateStockSchema(CamelModel):
    ticker: str
    reason: str
    added_at: datetime


class ScanMatchSchema(CamelModel):
    id: int | None
    ticker: str
    name: str
    reason: str
    rule_name: str
    price_at_trigger: float | None
    data_date: date | None
    is_notified: bool
    reasons: list[str]
    state: str


class ScanIssueSchema(CamelModel):
    ticker: str
    rule_name: str
    reason: str


class ScanSummarySchema(CamelModel):
    rules_evaluated: int
    stocks_scanned: int
    new_alerts: int
    excluded: int
    excluded_categories: list[str] = []
    matches: list[ScanMatchSchema]
    issues: list[ScanIssueSchema]


class CandidateRefreshSummarySchema(CamelModel):
    stocks_scanned: int
    added: int
    expired: int
    active_total: int


class ScanJobStartedSchema(CamelModel):
    job_id: str


class ScanJobSchema(ScanJobStartedSchema):
    status: Literal["running", "done", "failed"]
    done: int
    total: int
    summary: ScanSummarySchema | None
    error: str | None
