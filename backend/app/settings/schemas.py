from typing import Literal

from app.core.schemas import CamelModel


class SettingsSummarySchema(CamelModel):
    screening_interval_minutes: int
    candidate_pool_limit: int
    telegram_configured: bool
    excluded_etf_categories: list[str]


class TestTelegramResultSchema(CamelModel):
    success: bool
    message: str


class EtfExclusionSchema(CamelModel):
    categories: list[Literal["leveraged", "inverse", "bond", "futures"]]
