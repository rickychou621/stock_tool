from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class BacktestTask(Base):
    __tablename__ = "backtest_latest_task"
    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[str] = mapped_column(String(36))
    status: Mapped[str] = mapped_column(String(30))
    started_at: Mapped[datetime] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    rule_ids: Mapped[list] = mapped_column(JSON)
    tickers: Mapped[list] = mapped_column(JSON)
    total: Mapped[int] = mapped_column(default=0)
    succeeded: Mapped[int] = mapped_column(default=0)
    failed: Mapped[int] = mapped_column(default=0)
    errors: Mapped[list] = mapped_column(JSON, default=list)


class BacktestResult(Base):
    __tablename__ = "backtest_results"
    __table_args__ = (UniqueConstraint("ticker", "rule_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(10))
    stock_name: Mapped[str] = mapped_column(String(50))
    rule_id: Mapped[int] = mapped_column()
    rule_name: Mapped[str] = mapped_column(String(100))
    batch_id: Mapped[str] = mapped_column(String(36), index=True)
    stale: Mapped[bool] = mapped_column(Boolean, default=False)
    calculated_at: Mapped[datetime] = mapped_column(DateTime)
    # Entire pair's trades, signals, metrics and definition are replaced atomically.
    summary: Mapped[dict] = mapped_column(JSON)
    payload: Mapped[dict] = mapped_column(JSON)


class BacktestCoverage(Base):
    __tablename__ = "backtest_data_coverage"
    ticker: Mapped[str] = mapped_column(String(10), primary_key=True)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    dates: Mapped[list] = mapped_column(JSON)


class BacktestCalendarMonth(Base):
    __tablename__ = "backtest_calendar_months"
    month: Mapped[str] = mapped_column(String(7), primary_key=True)
    checked_on: Mapped[date] = mapped_column(Date)
    dates: Mapped[list] = mapped_column(JSON)
