from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.screening.models import CandidatePool


class ScreeningRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def get_active_candidates(self, limit: int) -> list[CandidatePool]:
        stmt = (
            select(CandidatePool)
            .where(CandidatePool.expired_at.is_(None))
            .order_by(CandidatePool.added_at.desc())
            .limit(limit)
        )
        return list(self._db.scalars(stmt))

    def get_all_active(self) -> list[CandidatePool]:
        """不設limit，供粗篩refresh邏輯比對目前候選池全貌用，不是給API直接暴露。"""
        stmt = select(CandidatePool).where(CandidatePool.expired_at.is_(None))
        return list(self._db.scalars(stmt))

    def create_candidate(self, ticker: str, reason: str) -> CandidatePool:
        candidate = CandidatePool(ticker=ticker, reason=reason)
        self._db.add(candidate)
        self._db.commit()
        self._db.refresh(candidate)
        return candidate

    def expire_candidate(self, candidate_id: int) -> None:
        candidate = self._db.get(CandidatePool, candidate_id)
        if candidate is None:
            return
        candidate.expired_at = datetime.utcnow()
        self._db.commit()

    def update_reason(self, candidate_id: int, reason: str) -> None:
        candidate = self._db.get(CandidatePool, candidate_id)
        if candidate is None:
            return
        candidate.reason = reason
        self._db.commit()
