from functools import lru_cache

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

    @property
    def database_url(self) -> str:
        return (
            f"mysql+pymysql://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
