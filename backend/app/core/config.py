from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """統一的設定入口。實際數值由環境變數注入(docker-compose用config/backend.env，
    本機開發可複製 .env.example 為 .env)，程式碼裡不寫死任何連線資訊或金鑰。"""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    db_host: str = "localhost"
    db_port: int = 3306
    db_name: str = "stock_tool"
    db_user: str = "stock_tool"
    db_password: str = ""

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    finmind_api_token: str = ""
    broker_api_key: str = ""
    broker_api_secret: str = ""

    # 篩選/排程參數：可隨時調整，不需改程式碼
    screening_interval_minutes: int = 5
    candidate_pool_limit: int = 10
    market_scan_workers: int = Field(default=5, gt=0, le=32)
    twse_min_request_interval_seconds: float = Field(default=3, gt=0, allow_inf_nan=False)
    finmind_scan_requests_per_minute: int = Field(default=4, gt=0, le=600)

    trade_fee_rate: float = Field(default=0.001425, ge=0, lt=1, allow_inf_nan=False)
    trade_fee_discount: float = Field(default=1.0, gt=0, le=1, allow_inf_nan=False)
    trade_tax_rate_stock: float = Field(default=0.003, ge=0, lt=1, allow_inf_nan=False)
    trade_tax_rate_etf: float = Field(default=0.001, ge=0, lt=1, allow_inf_nan=False)

    market_scan_notify_min_turnover: float = Field(
        default=10_000_000, ge=0, allow_inf_nan=False
    )

    signal_tracking_horizons: str = "1,5,10,20"

    @field_validator("signal_tracking_horizons")
    @classmethod
    def valid_horizons(cls, value):
        parts = value.split(",")
        if not parts or any(not p.strip().isdigit() or not 1 <= int(p) <= 60 for p in parts):
            raise ValueError("觀察期須為逗號分隔的 1～60 正整數")
        return ",".join(str(n) for n in sorted({int(p) for p in parts}))

    @property
    def tracking_horizons(self):
        return [int(n) for n in self.signal_tracking_horizons.split(",")]

    @property
    def database_url(self) -> str:
        return (
            f"mysql+pymysql://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
