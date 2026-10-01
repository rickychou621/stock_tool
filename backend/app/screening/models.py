from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class CandidatePool(Base):
    """兩階段粗篩產出的候選池，expired_at為NULL代表目前仍在池中。"""

    __tablename__ = "candidate_pool"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ticker: Mapped[str] = mapped_column(String(10), index=True)
    reason: Mapped[str] = mapped_column(String(255), default="")
    score: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    added_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    expired_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
