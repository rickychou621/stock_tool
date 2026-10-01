from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class AlertLog(Base):
    """規則觸發的告警歷史紀錄，亦作為防重複發送判斷的依據。"""

    __tablename__ = "alerts_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    rule_id: Mapped[int] = mapped_column(ForeignKey("watch_rules.id"), index=True)
    ticker: Mapped[str] = mapped_column(String(10), index=True)
    triggered_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    price_at_trigger: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    message: Mapped[str] = mapped_column(Text, default="")
    is_notified: Mapped[bool] = mapped_column(Boolean, default=False)
