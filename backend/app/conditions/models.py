"""條件庫清單、每日條件結果快取的資料表。"""

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class ConditionCatalog(Base):
    """供前端動態組裝規則時查詢可用條件與參數規格，由後端啟動時依registry內容同步寫入。"""

    __tablename__ = "condition_catalog"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(String(500), default="")
    required_timeframe: Mapped[str] = mapped_column(String(10))
    update_frequency: Mapped[str] = mapped_column(String(10))
    param_schema: Mapped[dict] = mapped_column(JSON, default=dict)


class DailyConditionCache(Base):
    """每日/月頻條件的計算結果快取，供混合頻率規則於盤中即時評估時直接取用，不重算日頻邏輯。"""

    __tablename__ = "daily_condition_cache"
    __table_args__ = (UniqueConstraint("ticker", "condition_id", "params_hash", "trade_date"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ticker: Mapped[str] = mapped_column(String(10), index=True)
    condition_id: Mapped[str] = mapped_column(String(50), ForeignKey("condition_catalog.id"))
    params_hash: Mapped[str] = mapped_column(String(64))
    trade_date: Mapped[date] = mapped_column(Date)
    result: Mapped[bool] = mapped_column(Boolean)
    computed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
