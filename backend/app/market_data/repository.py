from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import exists, func, select
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.orm import Session

from app.market_data.models import Stock, StockDividendEvent, StockPriceDaily


class MarketDataRepository:
    def __init__(self, db: Session, *, commit=True) -> None:
        self._db = db
        self._commit = commit

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
            turnover=func.coalesce(stmt.inserted.turnover, StockPriceDaily.turnover),
        )
        self._db.execute(stmt)
        if self._commit:
            self._db.commit()
        else:
            self._db.flush()
        return len(rows)

    def upsert_dividend_events(self, ticker: str, events: list[dict]) -> int:
        if not events:
            return 0

        rows = [{"ticker": ticker, **event} for event in events]
        updates = (
            "cash_dividend",
            "stock_dividend_ratio",
            "cash_capital_increase_ratio",
            "cash_capital_increase_price",
        )
        if self._db.bind.dialect.name == "sqlite":
            from sqlalchemy.dialects.sqlite import insert as sqlite_insert

            stmt = sqlite_insert(StockDividendEvent).values(rows)
            stmt = stmt.on_conflict_do_update(
                index_elements=["ticker", "ex_dividend_date"],
                set_={key: getattr(stmt.excluded, key) for key in updates},
            )
        else:
            stmt = mysql_insert(StockDividendEvent).values(rows)
            stmt = stmt.on_duplicate_key_update(
                **{key: getattr(stmt.inserted, key) for key in updates}
            )
        self._db.execute(stmt)
        if self._commit:
            self._db.commit()
        else:
            self._db.flush()
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

    def get_names(self, tickers: list[str]) -> dict[str, str]:
        if not tickers:
            return {}
        return dict(self._db.execute(
            select(Stock.ticker, Stock.name).where(Stock.ticker.in_(tickers))
        ).all())

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
            for name in ("open", "high", "low", "close"):
                # Match NUMERIC(10, 2); unrounded floats otherwise dirty unchanged
                # history on every backfill day and hold unnecessary row locks.
                value = Decimal(str(values[name])).quantize(Decimal("0.01"), ROUND_HALF_UP)
                if getattr(bar, f"adj_{name}") != value:
                    setattr(bar, f"adj_{name}", value)
        if self._commit:
            self._db.commit()
        else:
            self._db.flush()

    def upsert_market_bars(self, rows):
        """Atomic caller-owned write; bounded statements for a complete market day."""
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert

        for offset in range(0, len(rows), 400):
            chunk = rows[offset : offset + 400]
            if self._db.bind.dialect.name == "sqlite":
                stmt = sqlite_insert(StockPriceDaily).values(chunk)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["ticker", "trade_date"],
                    set_={
                        k: getattr(stmt.excluded, k)
                        for k in chunk[0]
                        if k not in ("ticker", "trade_date")
                    },
                )
            else:
                stmt = mysql_insert(StockPriceDaily).values(chunk)
                stmt = stmt.on_duplicate_key_update(
                    **{
                        k: getattr(stmt.inserted, k)
                        for k in chunk[0]
                        if k not in ("ticker", "trade_date")
                    }
                )
            self._db.execute(stmt)
        self._db.flush()
