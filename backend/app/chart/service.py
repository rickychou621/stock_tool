from sqlalchemy.orm import Session

from app.chart.repository import ChartRepository
from app.market_data.models import StockPriceDaily


class ChartService:
    def __init__(self, db: Session) -> None:
        self._repository = ChartRepository(db)

    def get_price_history(self, ticker: str, limit: int) -> list[StockPriceDaily]:
        return self._repository.get_daily_bars(ticker, limit)
