from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.market_data.models import StockPriceDaily


class ChartRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def get_daily_bars(self, ticker: str, limit: int) -> list[StockPriceDaily]:
        stmt = (
            select(StockPriceDaily)
            .where(StockPriceDaily.ticker == ticker)
            .order_by(StockPriceDaily.trade_date.desc())
            .limit(limit)
        )
        rows = list(self._db.scalars(stmt))
        return list(reversed(rows))

    def get_daily_bars_in_range(
        self, ticker: str, start: date, end: date | None,
    ) -> list[StockPriceDaily]:
        stmt = select(StockPriceDaily).where(
            StockPriceDaily.ticker == ticker, StockPriceDaily.trade_date >= start,
        )
        if end is not None:
            stmt = stmt.where(StockPriceDaily.trade_date <= end)
        return list(self._db.scalars(stmt.order_by(StockPriceDaily.trade_date).limit(1000)))
