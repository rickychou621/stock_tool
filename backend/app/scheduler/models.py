"""排程設定、單筆執行摘要及永久錯誤紀錄。時間以 UTC 儲存。"""

from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class ScheduleSettings(Base):
    __tablename__ = "watchlist_schedule_settings"
    id: Mapped[int] = mapped_column(primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # NULL means initial default: all enabled rules; [] explicitly means no evaluation.
    rule_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    last_attempt_date: Mapped[date | None] = mapped_column(Date, nullable=True)


class ScheduleRun(Base):
    __tablename__ = "watchlist_schedule_latest"
    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[str] = mapped_column(String(36))
    trade_date: Mapped[date] = mapped_column(Date)
    started_at: Mapped[datetime] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(30))
    total: Mapped[int] = mapped_column(default=0)
    succeeded: Mapped[int] = mapped_column(default=0)
    failed: Mapped[int] = mapped_column(default=0)


class ScheduleError(Base):
    __tablename__ = "watchlist_schedule_errors"
    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[str] = mapped_column(String(36), index=True)
    ticker: Mapped[str | None] = mapped_column(String(10), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime)
    reason: Mapped[str] = mapped_column(Text)
