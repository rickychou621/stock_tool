from typing import Literal

from pydantic import Field

from app.core.schemas import CamelModel


class SettingsSummarySchema(CamelModel):
    screening_interval_minutes: int
    candidate_pool_limit: int
    telegram_configured: bool
    excluded_etf_categories: list[str]
    large_stop_distance_pct: float


class TestTelegramResultSchema(CamelModel):
    success: bool
    message: str


class EtfExclusionSchema(CamelModel):
    categories: list[Literal["leveraged", "inverse", "bond", "futures"]]


class StopDistanceSchema(CamelModel):
    large_stop_distance_pct: float = Field(gt=0, lt=1)
