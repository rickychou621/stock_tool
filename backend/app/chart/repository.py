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
