from app.core.schemas import CamelModel


class SettingsSummarySchema(CamelModel):
    screening_interval_minutes: int
    candidate_pool_limit: int
    telegram_configured: bool


class TestTelegramResultSchema(CamelModel):
    success: bool
    message: str
