from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class HoldingsWatchlist(Base):
    """手動維護的持股觀察清單，獨立於粗篩候選池，固定監控不受粗篩結果影響。"""

    __tablename__ = "holdings_watchlist"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(10), index=True)
    entry_price: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    entry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class WatchlistEvaluation(Base):
    __tablename__ = "watchlist_evaluations"
    __table_args__ = (UniqueConstraint("item_id", "rule_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("holdings_watchlist.id", ondelete="CASCADE"))
    rule_id: Mapped[int] = mapped_column(ForeignKey("watch_rules.id", ondelete="CASCADE"))
    result: Mapped[dict] = mapped_column(JSON)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime)
    data_version: Mapped[int] = mapped_column()
    rule_fingerprint: Mapped[str] = mapped_column(String(64))
