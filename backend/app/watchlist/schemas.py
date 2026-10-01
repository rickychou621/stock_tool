"""持股清單對外API的請求/回應格式。"""

from datetime import date, datetime

from pydantic import Field, field_validator

from app.core.schemas import CamelModel


class WatchlistItemSchema(CamelModel):
    id: int
    ticker: str
    entry_price: float | None
    entry_date: date | None
    notes: str
    is_active: bool
    stock_name: str = ""
    sector: str = ""


class WatchlistCreateSchema(CamelModel):
    ticker: str = Field(min_length=1, max_length=10, pattern=r"^[A-Z0-9]+$")
    entry_price: float | None = None
    entry_date: date | None = None
    notes: str = ""

    @field_validator("ticker", mode="before")
    @classmethod
    def normalize_ticker(cls, value: str) -> str:
        return value.strip().upper() if isinstance(value, str) else value


class WatchlistUpdateSchema(CamelModel):
    entry_price: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    entry_date: date | None = None
    notes: str = Field(default="", max_length=5000)
    sector: str = Field(default="", max_length=80)


class EvaluateWatchlistSchema(CamelModel):
    rule_ids: list[int] = Field(min_length=1, max_length=50)


class SavedEvaluationSchema(CamelModel):
    item_id: int
    rule_id: int
    rule_name: str
    result: dict
    evaluated_at: datetime
    stale: bool
