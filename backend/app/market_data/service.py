from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.data_source.finmind_client import FinMindClient
from app.market_data.models import Stock
from app.market_data.price_adjustment import DividendEvent, PriceBar, apply_adjustment
from app.market_data.repository import MarketDataRepository


class MarketDataService:
    def __init__(self, db: Session, client=None) -> None:
        self._db = db
        self._repository = MarketDataRepository(db)
        self._client = client or FinMindClient()

    def sync_daily_prices(
        self, ticker: str, days: int = 180, *, start_date=None, end_date=None, fetch_prices=True
    ) -> int:
        if start_date is not None:
            return self._sync_validated_range(ticker, start_date, end_date, fetch_prices)

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

    def _recalculate_adjusted_prices(self, ticker: str, *, validate=False) -> None:
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

        if validate and price_bars:
            latest = max(b.trade_date for b in price_bars)
            dividend_events = [e for e in dividend_events if e.ex_dividend_date <= latest]
        adjusted_by_date = apply_adjustment(price_bars, dividend_events)
        if validate:
            from app.market_data.validation import valid_ohlcv

            for bar in db_bars:
                adjusted = dict(adjusted_by_date[bar.trade_date], volume=bar.volume)
                if valid_ohlcv(bar) and not valid_ohlcv(adjusted):
                    raise ValueError(f"{bar.trade_date} 還原股價無效，交易已回滾")
        self._repository.update_adjusted_prices(ticker, adjusted_by_date, db_bars)

    def _sync_validated_range(self, ticker, start, end, fetch_prices=True):
        """Stage-three opt-in: all network/validation before a short atomic write.

        Reuse source, repositories and adjustment; invalid responses never replace good bars.
        Only transient DB deadlock/lock-timeout writes may retry, never HTTP calls.
        """
        from datetime import timedelta
        from math import isfinite

        from sqlalchemy.exc import OperationalError

        from app.market_data.validation import valid_ohlcv

        self._db.rollback()  # End any read snapshot before waiting for the API budget.
        bars = (
            self._client.get_daily_price(ticker, start_date=start, end_date=end)
            if fetch_prices
            else []
        )
        # FinMind filters TaiwanStockDividend by distribution record date, which
        # differs from the ex-date (e.g. 0050 2026-07-27 vs 2026-07-21).
        # Query a bounded overlap, then apply the requested actual ex-date range.
        events = self._client.get_dividend_events(
            ticker, start_date=start - timedelta(days=31), end_date=end + timedelta(days=31)
        )
        events = [event for event in events if start <= event["ex_dividend_date"] <= end]
        for bar in bars:
            if not start <= bar["trade_date"] <= end or not valid_ohlcv(bar):
                raise ValueError(f"{bar['trade_date']} FinMind 行情無效，未寫入")
            value = bar.get("turnover")
            if value is not None and (not isfinite(float(value)) or float(value) < 0):
                raise ValueError("FinMind 實際成交金額無效")
        if len({b["trade_date"] for b in bars}) != len(bars):
            raise ValueError("FinMind 行情日期重複")
        for event in events:
            if not start <= event["ex_dividend_date"] <= end or any(
                not isfinite(float(v)) or float(v) < 0
                for k, v in event.items()
                if k != "ex_dividend_date"
            ):
                raise ValueError("FinMind 股利資料無效，未寫入")
        original_repository = self._repository
        self._repository = MarketDataRepository(self._db, commit=False)
        try:
            for attempt in range(3):
                try:
                    # Serialize stage-three same-stock writes; unique keys also protect upserts.
                    self._db.execute(
                        select(Stock.id).where(Stock.ticker == ticker).with_for_update()
                    )
                    self._repository.upsert_daily_bars(ticker, bars)
                    self._repository.upsert_dividend_events(ticker, events)
                    self._recalculate_adjusted_prices(ticker, validate=True)
                    self._db.execute(
                        update(Stock)
                        .where(Stock.ticker == ticker)
                        .values(data_version=Stock.data_version + 1)
                    )
                    self._db.commit()
                    return len(bars)
                except OperationalError as exc:
                    self._db.rollback()
                    if attempt == 2 or getattr(exc.orig, "args", [None])[0] not in (1205, 1213):
                        raise
                except Exception:
                    self._db.rollback()
                    raise
        finally:
            self._repository = original_repository
