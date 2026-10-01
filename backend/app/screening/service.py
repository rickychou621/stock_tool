from sqlalchemy.orm import Session

from app.screening.models import CandidatePool
from app.screening.repository import ScreeningRepository


class ScreeningService:
    def __init__(self, db: Session) -> None:
        self._repository = ScreeningRepository(db)

    def get_candidates(self, limit: int) -> list[CandidatePool]:
        return self._repository.get_active_candidates(limit)
