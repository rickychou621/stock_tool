from sqlalchemy import select
from sqlalchemy.orm import Session

from app.watchlist.models import HoldingsWatchlist


class WatchlistRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def list_active(self, limit: int) -> list[HoldingsWatchlist]:
        stmt = (
            select(HoldingsWatchlist)
            .where(HoldingsWatchlist.is_active.is_(True))
            .order_by(HoldingsWatchlist.created_at.desc())
            .limit(limit)
        )
        return list(self._db.scalars(stmt))

    def create(self, item: HoldingsWatchlist) -> HoldingsWatchlist:
        self._db.add(item)
        self._db.commit()
        self._db.refresh(item)
        return item

    def deactivate(self, item_id: int) -> HoldingsWatchlist | None:
        item = self._db.get(HoldingsWatchlist, item_id)
        if item is None:
            return None
        item.is_active = False
        self._db.commit()
        self._db.refresh(item)
        return item

    def find_active(self, ticker: str) -> HoldingsWatchlist | None:
        return self._db.scalar(
            select(HoldingsWatchlist)
            .where(
                HoldingsWatchlist.ticker == ticker,
                HoldingsWatchlist.is_active.is_(True),
            )
            .limit(1)
        )
