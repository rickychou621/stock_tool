from sqlalchemy import exists, select
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.orm import Session

from app.market_data.models import Stock, StockDividendEvent, StockPriceDaily


class MarketDataRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def upsert_daily_bars(self, ticker: str, bars: list[dict]) -> int:
        if not bars:
            return 0

        rows = [{"ticker": ticker, **bar} for bar in bars]
        stmt = mysql_insert(StockPriceDaily).values(rows)
        stmt = stmt.on_duplicate_key_update(
            open=stmt.inserted.open,
            high=stmt.inserted.high,
            low=stmt.inserted.low,
            close=stmt.inserted.close,
            volume=stmt.inserted.volume,
        )
        self._db.execute(stmt)
        self._db.commit()
        return len(rows)

    def upsert_dividend_events(self, ticker: str, events: list[dict]) -> int:
        if not events:
            return 0

        rows = [{"ticker": ticker, **event} for event in events]
        stmt = mysql_insert(StockDividendEvent).values(rows)
        stmt = stmt.on_duplicate_key_update(
            cash_dividend=stmt.inserted.cash_dividend,
            stock_dividend_ratio=stmt.inserted.stock_dividend_ratio,
            cash_capital_increase_ratio=stmt.inserted.cash_capital_increase_ratio,
            cash_capital_increase_price=stmt.inserted.cash_capital_increase_price,
        )
        self._db.execute(stmt)
        self._db.commit()
        return len(rows)

    def get_all_bars(self, ticker: str) -> list[StockPriceDaily]:
        stmt = (
            select(StockPriceDaily)
            .where(StockPriceDaily.ticker == ticker)
            .order_by(StockPriceDaily.trade_date)
        )
        return list(self._db.scalars(stmt))

    def get_all_events(self, ticker: str) -> list[StockDividendEvent]:
        stmt = (
            select(StockDividendEvent)
            .where(StockDividendEvent.ticker == ticker)
            .order_by(StockDividendEvent.ex_dividend_date)
        )
        return list(self._db.scalars(stmt))

    def get_latest_bar(self, ticker: str) -> StockPriceDaily | None:
        stmt = (
            select(StockPriceDaily)
            .where(StockPriceDaily.ticker == ticker)
            .order_by(StockPriceDaily.trade_date.desc())
            .limit(1)
        )
        return self._db.scalars(stmt).first()

    def list_chartable_tickers(self) -> list[str]:
        """有日K資料、可以被規則評估的股票代號清單。"""
        stmt = (
            select(Stock.ticker)
            .where(Stock.is_active.is_(True))
            .where(exists().where(StockPriceDaily.ticker == Stock.ticker))
        )
        return list(self._db.scalars(stmt))

    def update_adjusted_prices(
        self, ticker: str, adjusted_by_date: dict, bars: list[StockPriceDaily]
    ) -> None:
        for bar in bars:
            values = adjusted_by_date.get(bar.trade_date)
            if values is None:
                continue
            bar.adj_open = values["open"]
            bar.adj_high = values["high"]
            bar.adj_low = values["low"]
            bar.adj_close = values["close"]
        self._db.commit()
