from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class WatchRule(Base):
    """使用者自由組合的監控規則。"""

    __tablename__ = "watch_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    logic_operator: Mapped[str] = mapped_column(String(5), default="AND")
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    conditions: Mapped[list["WatchRuleCondition"]] = relationship(
        back_populates="rule", cascade="all, delete-orphan"
    )


class WatchRuleCondition(Base):
    """規則所引用的條件與其實際參數值，規則與條件為多對多關係。"""

    __tablename__ = "watch_rule_conditions"

    id: Mapped[int] = mapped_column(primary_key=True)
    rule_id: Mapped[int] = mapped_column(ForeignKey("watch_rules.id"))
    condition_id: Mapped[str] = mapped_column(ForeignKey("condition_catalog.id"))
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    rule: Mapped["WatchRule"] = relationship(back_populates="conditions")
