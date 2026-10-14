"""Stage-three settings, current universe, two task slots and atomic publication."""

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class MarketInstrument(Base):
    __tablename__ = "market_scan_instruments"
    ticker: Mapped[str] = mapped_column(String(10), ForeignKey("stocks.ticker"), primary_key=True)
    market: Mapped[str] = mapped_column(String(20), default="TWSE")
    kind: Mapped[str] = mapped_column(String(20))
    listed_on: Mapped[date] = mapped_column(Date)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)


class ScanSettings(Base):
    __tablename__ = "market_scan_settings"
    id: Mapped[int] = mapped_column(primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    rule_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    last_attempt_date: Mapped[date | None] = mapped_column(Date, nullable=True)


class ScanTask(Base):
    __tablename__ = "market_scan_tasks"
    kind: Mapped[str] = mapped_column(String(16), primary_key=True)
    batch_id: Mapped[str] = mapped_column(String(36))
    source: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(30))
    started_at: Mapped[datetime] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    baseline: Mapped[date | None] = mapped_column(Date, nullable=True)
    rules: Mapped[list] = mapped_column(JSON, default=list)
    total: Mapped[int] = mapped_column(Integer, default=0)
    processed: Mapped[int] = mapped_column(Integer, default=0)
    succeeded: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    insufficient: Mapped[int] = mapped_column(Integer, default=0)
    warnings: Mapped[list] = mapped_column(JSON, default=list)


class ScanError(Base):
    __tablename__ = "market_scan_errors"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), index=True)
    batch_id: Mapped[str] = mapped_column(String(36))
    ticker: Mapped[str | None] = mapped_column(String(10), nullable=True)
    rule_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(30))
    reason: Mapped[str] = mapped_column(String(1000))


class ScanPublication(Base):
    __tablename__ = "market_scan_publication"
    id: Mapped[int] = mapped_column(primary_key=True)
    metadata_json: Mapped[dict] = mapped_column(JSON)


class ScanCandidate(Base):
    __tablename__ = "market_scan_candidates"
    __table_args__ = (UniqueConstraint("ticker", "rule_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(10), index=True)
    stock_name: Mapped[str] = mapped_column(String(50))
    kind: Mapped[str] = mapped_column(String(20), index=True)
    rule_id: Mapped[int] = mapped_column(Integer, index=True)
    rule_name: Mapped[str] = mapped_column(String(100))
    batch_id: Mapped[str] = mapped_column(String(36), index=True)
    status: Mapped[str] = mapped_column(String(30), index=True)
    reason: Mapped[str] = mapped_column(String(2000))
    status_reason: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    indicators: Mapped[dict] = mapped_column(JSON)
    close: Mapped[float] = mapped_column(Numeric(14, 4), index=True)
    price_date: Mapped[date] = mapped_column(Date, index=True)
    volume: Mapped[int] = mapped_column(BigInteger, index=True)
    turnover: Mapped[float | None] = mapped_column(Numeric(22, 2), nullable=True, index=True)
    scanned_at: Mapped[datetime] = mapped_column(DateTime)
    older_quote: Mapped[bool] = mapped_column(Boolean)


class CandidateIndicator(Base):
    __tablename__ = "market_scan_indicators"
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("market_scan_candidates.id", ondelete="CASCADE"), primary_key=True
    )
    name: Mapped[str] = mapped_column(String(120), primary_key=True)
    value: Mapped[float] = mapped_column(Float, index=True)


class ScanCoverage(Base):
    __tablename__ = "market_scan_coverage"
    ticker: Mapped[str] = mapped_column(String(10), primary_key=True)
    # Source-confirmed intervals + returned dates. Empty suspension/listing gaps are explicit.
    ranges: Mapped[list] = mapped_column(JSON, default=list)
