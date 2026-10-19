"""Public camelCase contracts, including finite numeric indicator values."""

from datetime import date

from app.core.schemas import CamelModel


class RuleSnapshot(CamelModel):
    id: int
    name: str


class SettingsResponse(CamelModel):
    enabled: bool
    rule_ids: list[int]
    workers: int
    requests_per_minute: int


class Accepted(CamelModel):
    batch_id: str


class TaskResponse(CamelModel):
    kind: str
    batch_id: str
    source: str
    status: str
    started_at: str
    finished_at: str | None
    baseline: date | None
    rules: list[RuleSnapshot]
    total: int
    processed: int
    succeeded: int
    failed: int
    insufficient: int
    warnings: list[str]


class TasksResponse(CamelModel):
    scan: TaskResponse | None
    initialize: TaskResponse | None


class SummaryResponse(CamelModel):
    batch_id: str
    source: str
    status: str
    finished_at: str
    baseline: date
    rules: list[RuleSnapshot]
    total: int
    succeeded: int
    failed: int
    insufficient: int
    continuing: int = 0
    normal_count: int
    abnormal_count: int
    warnings: list[str]


class CandidateResponse(CamelModel):
    id: int
    ticker: str
    stock_name: str
    kind: str
    rule_id: int
    rule_name: str
    batch_id: str
    status: str
    status_reason: str | None
    reason: str
    indicators: dict[str, float]
    close: float
    price_date: date
    volume: int
    turnover: float | None
    scanned_at: str
    older_quote: bool


class ErrorResponse(CamelModel):
    ticker: str | None
    rule_id: int | None
    status: str
    reason: str


class PageResponse[T](CamelModel):
    total: int
    page: int
    page_size: int
    items: list[T]
