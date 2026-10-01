from sqlalchemy import update
from sqlalchemy.orm import Session

from app.data_source.finmind_client import FinMindClient
from app.market_data.models import Stock
from app.market_data.price_adjustment import DividendEvent, PriceBar, apply_adjustment
from app.market_data.repository import MarketDataRepository


class MarketDataService:
    def __init__(self, db: Session) -> None:
        self._db = db
        self._repository = MarketDataRepository(db)
        self._client = FinMindClient()

    def sync_daily_prices(self, ticker: str, days: int = 180) -> int:
        bars = self._client.get_daily_price(ticker, days=days)
        # Invalidate saved evaluations before any committed price/dividend changes.
        self._db.execute(
            update(Stock).where(Stock.ticker == ticker).values(data_version=Stock.data_version + 1)
        )
        self._db.commit()
        rows_synced = self._repository.upsert_daily_bars(ticker, bars)

        events = self._client.get_dividend_events(ticker, days=max(days, 730))
        self._repository.upsert_dividend_events(ticker, events)

        self._recalculate_adjusted_prices(ticker)
        return rows_synced

    def _recalculate_adjusted_prices(self, ticker: str) -> None:
        """用目前DB裡存的全部日K+股利事件重算還原股價，蓋掉整段歷史
        (股利事件不常變動，每次sync都整段重算一次，資料量不大，成本可以忽略)。"""
        db_bars = self._repository.get_all_bars(ticker)
        db_events = self._repository.get_all_events(ticker)

        price_bars = [
            PriceBar(
                trade_date=bar.trade_date,
                open=float(bar.open),
                high=float(bar.high),
                low=float(bar.low),
                close=float(bar.close),
            )
            for bar in db_bars
        ]
        dividend_events = [
            DividendEvent(
                ex_dividend_date=event.ex_dividend_date,
                cash_dividend=float(event.cash_dividend),
                stock_dividend_ratio=float(event.stock_dividend_ratio),
                cash_capital_increase_ratio=float(event.cash_capital_increase_ratio),
                cash_capital_increase_price=float(event.cash_capital_increase_price),
            )
            for event in db_events
        ]

        adjusted_by_date = apply_adjustment(price_bars, dividend_events)
        self._repository.update_adjusted_prices(ticker, adjusted_by_date, db_bars)
