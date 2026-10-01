"""候選池對外API的請求/回應格式。"""

from datetime import date, datetime

from app.core.schemas import CamelModel


class CandidateStockSchema(CamelModel):
    ticker: str
    reason: str
    added_at: datetime


class ScanMatchSchema(CamelModel):
    id: int
    ticker: str
    rule_name: str
    price_at_trigger: float | None
    data_date: date | None
    is_notified: bool
    reasons: list[str]


class ScanIssueSchema(CamelModel):
    ticker: str
    rule_name: str
    reason: str


class ScanSummarySchema(CamelModel):
    rules_evaluated: int
    stocks_scanned: int
    new_alerts: int
    matches: list[ScanMatchSchema]
    issues: list[ScanIssueSchema]


class CandidateRefreshSummarySchema(CamelModel):
    stocks_scanned: int
    added: int
    expired: int
    active_total: int
