from sqlalchemy.orm import Session

from app.watchlist.models import HoldingsWatchlist
from app.watchlist.repository import WatchlistRepository
from app.watchlist.schemas import WatchlistCreateSchema


class WatchlistService:
    def __init__(self, db: Session) -> None:
        self._repository = WatchlistRepository(db)

    def list_active(self, limit: int) -> list[HoldingsWatchlist]:
        return self._repository.list_active(limit)

    def add_holding(self, payload: WatchlistCreateSchema) -> HoldingsWatchlist:
        existing = self._repository.find_active(payload.ticker)
        if existing is not None:
            return existing
        item = HoldingsWatchlist(
            ticker=payload.ticker,
            entry_price=payload.entry_price,
            entry_date=payload.entry_date,
            notes=payload.notes,
        )
        return self._repository.create(item)

    def remove_holding(self, item_id: int) -> HoldingsWatchlist | None:
        return self._repository.deactivate(item_id)
