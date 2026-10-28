import random
import time
from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.data_source.finmind_client import FinMindClient
from app.market_data.models import Stock, StockPriceEvent
from app.market_data.price_adjustment import DividendEvent, PriceBar, PriceEvent, apply_adjustment
from app.market_data.repository import MarketDataRepository

_sleep = time.sleep


class MarketDataService:
    def __init__(self, db: Session, client=None) -> None:
        self._db = db
        self._repository = MarketDataRepository(db)
        self._client = client or FinMindClient()

    def sync_daily_prices(
        self,
        ticker: str,
        days: int = 180,
        *,
        start_date=None,
        end_date=None,
        fetch_prices=True,
    ) -> int:
        if start_date is not None:
            return self._sync_validated_range(ticker, start_date, end_date, fetch_prices)

        self._db.rollback()
        bars = self._client.get_daily_price(ticker, days=days)
        events = self._client.get_dividend_events(ticker, days=max(days, 730))
        return self._sync_rows(ticker, bars, events, validate=False)

    def _data_snapshot(self, ticker):
        from app.market_data.models import StockDividendEvent, StockPriceDaily

        result = []
        for model, date_field in (
            (StockPriceDaily, "trade_date"),
            (StockDividendEvent, "ex_dividend_date"),
        ):
            columns = [
                c for c in model.__table__.columns if c.name not in ("id", "ticker", "created_at")
            ]
            stmt = select(*columns).where(model.ticker == ticker)
            result.append(
                tuple(
                    tuple(
                        v if v is None or c.name == date_field else Decimal(str(v))
                        for c, v in zip(columns, row, strict=True)
                    )
                    for row in self._db.execute(stmt.order_by(getattr(model, date_field)))
                )
            )
        return tuple(result)

    def _bump_if_changed(self, ticker, before):
        if before != self._data_snapshot(ticker):
            self._db.execute(
                update(Stock)
                .where(Stock.ticker == ticker)
                .values(data_version=Stock.data_version + 1)
            )

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
        price_events = self.load_price_events(ticker)
        adjusted_by_date = apply_adjustment(price_bars, dividend_events, price_events)
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
        return self._sync_rows(ticker, bars, events, validate=True)

    def _sync_rows(self, ticker, bars, events, *, validate):
        from sqlalchemy.exc import OperationalError

        original_repository = self._repository
        self._repository = MarketDataRepository(self._db, commit=False)
        try:
            for attempt in range(4):
                try:
                    # Serialize same-stock writes; unique keys also protect upserts.
                    self._db.execute(
                        select(Stock.id).where(Stock.ticker == ticker).with_for_update()
                    )
                    before = self._data_snapshot(ticker)
                    self._repository.upsert_daily_bars(ticker, bars)
                    self._repository.upsert_dividend_events(ticker, events)
                    self._db.expire_all()
                    self._recalculate_adjusted_prices(ticker, validate=validate)
                    self._bump_if_changed(ticker, before)
                    self._db.commit()
                    return len(bars)
                except OperationalError as exc:
                    self._db.rollback()
                    if attempt == 3 or getattr(exc.orig, "args", [None])[0] not in (1205, 1213):
                        raise
                    _sleep(random.uniform(0.2, 1.0) * (attempt + 1))
                except Exception:
                    self._db.rollback()
                    raise
        finally:
            self._repository = original_repository

    def import_market_day(self, day, rows):
        """No commit: prices, adjustments and coverage belong to one day transaction."""
        from decimal import Decimal

        from sqlalchemy import func

        from app.market_data.models import StockDividendEvent, StockPriceDaily
        from app.market_data.validation import valid_ohlcv

        if not rows:
            return []
        tickers = sorted({r["ticker"] for r in rows})
        if len(tickers) != len(rows) or any(
            r["trade_date"] != day or not valid_ohlcv(r) for r in rows
        ):
            raise ValueError("批次行情日期、代號或 OHLCV 無效")
        self._db.execute(
            select(Stock.id)
            .where(Stock.ticker.in_(tickers))
            .order_by(Stock.ticker)
            .with_for_update()
        ).all()
        latest = dict(
            self._db.execute(
                select(StockPriceDaily.ticker, func.max(StockPriceDaily.trade_date))
                .where(StockPriceDaily.ticker.in_(tickers))
                .group_by(StockPriceDaily.ticker)
            ).all()
        )
        old = {
            b.ticker: b
            for b in self._db.scalars(
                select(StockPriceDaily).where(
                    StockPriceDaily.ticker.in_(tickers), StockPriceDaily.trade_date == day
                )
            )
        }
        event_dates = self._db.execute(
            select(StockDividendEvent.ticker, StockDividendEvent.ex_dividend_date).where(
                StockDividendEvent.ticker.in_(tickers)
            )
        ).all()
        event_dates += self._db.execute(
            select(StockPriceEvent.ticker, StockPriceEvent.event_date).where(
                StockPriceEvent.ticker.in_(tickers)
            )
        ).all()
        later_events = {t for t, ex in event_dates if day < ex <= latest.get(t, day)}
        # Filling a missing historical day after the last known dividend cannot
        # change any adjustment factor. Its raw OHLC is already the correct basis.
        # Revisions and inserts preceding a known event still recalculate history.
        revised = {
            r["ticker"]
            for r in rows
            if r["ticker"] in old
            and any(
                Decimal(str(r[k])) != Decimal(str(getattr(old[r["ticker"]], k)))
                for k in ("open", "high", "low", "close")
            )
        }
        recalculate = {
            t
            for t, last in latest.items()
            if last >= day and (t in revised or t in later_events and t not in old)
        }
        recalculate.update(
            t
            for t, bar in old.items()
            if any(getattr(bar, f"adj_{k}") is None for k in ("open", "high", "low", "close"))
        )
        recalculate.update(t for t, ex in event_dates if t in latest and latest[t] < ex <= day)
        warnings, prepared = [], []
        for row in rows:
            ticker = row["ticker"]
            previous = old.get(ticker)
            if (
                previous is not None
                and valid_ohlcv(previous)
                and any(
                    abs(Decimal(str(row[k])) - getattr(previous, k)) > Decimal("0.01")
                    for k in ("open", "high", "low", "close")
                )
            ):
                warnings.append((ticker, f"{day} OHLC 與既有資料差異超過 0.01 元，以證交所為準"))
            adjusted = apply_adjustment(
                [
                    PriceBar(
                        trade_date=day,
                        **{k: float(row[k]) for k in ("open", "high", "low", "close")},
                    )
                ],
                [],
            )[day]
            if previous is not None and ticker not in recalculate:
                adjusted = {k: getattr(previous, f"adj_{k}") for k in adjusted}
            prepared.append({**row, **{f"adj_{k}": v for k, v in adjusted.items()}})
        fields = (
            "open",
            "high",
            "low",
            "close",
            "volume",
            "turnover",
            "adj_open",
            "adj_high",
            "adj_low",
            "adj_close",
        )

        def values(bar):
            return tuple(
                None if getattr(bar, k) is None else Decimal(str(getattr(bar, k))) for k in fields
            )

        before = {t: values(bar) for t, bar in old.items()}
        history = {t: self._data_snapshot(t) for t in recalculate}
        original = self._repository
        self._repository = MarketDataRepository(self._db, commit=False)
        try:
            self._repository.upsert_market_bars(prepared)
            # Bulk SQL bypasses identity-map values read above.
            self._db.expire_all()
            for ticker in sorted(recalculate):
                self._recalculate_adjusted_prices(ticker, validate=True)
            changed = {
                bar.ticker
                for bar in self._db.scalars(
                    select(StockPriceDaily).where(
                        StockPriceDaily.ticker.in_(tickers), StockPriceDaily.trade_date == day
                    )
                )
                if before.get(bar.ticker) != values(bar)
            }
            changed.update(t for t in recalculate if history[t] != self._data_snapshot(t))
            if changed:
                self._db.execute(
                    update(Stock)
                    .where(Stock.ticker.in_(changed))
                    .values(data_version=Stock.data_version + 1)
                )
            self._db.flush()
        finally:
            self._repository = original
        return warnings

    def load_price_events(self, ticker):
        return [
            PriceEvent(e.event_date, float(e.before_close), float(e.reference_price))
            for e in self._db.scalars(
                select(StockPriceEvent).where(StockPriceEvent.ticker == ticker)
            )
        ]

    def store_price_events(self, ticker, rows):
        """Caller owns the transaction; corrections invalidate old backtests too."""
        from decimal import Decimal

        from app.backtest.models import BacktestResult

        self._db.execute(select(Stock.id).where(Stock.ticker == ticker).with_for_update())
        existing = {
            (e.event_date, e.event_type): e
            for e in self._db.scalars(
                select(StockPriceEvent).where(StockPriceEvent.ticker == ticker)
            )
        }
        changed = False
        for row in rows:
            if row["ticker"] != ticker:
                raise ValueError("價格事件代號不符")
            key = row["event_date"], row["event_type"]
            old = existing.get(key)
            if old is None:
                old = StockPriceEvent(**row)
                existing[key] = old
                self._db.add(old)
                changed = True
            elif any(
                Decimal(str(getattr(old, k))) != Decimal(str(row[k]))
                for k in ("before_close", "reference_price")
            ):
                old.before_close, old.reference_price = row["before_close"], row["reference_price"]
                old.source = row["source"]
                changed = True
        if changed:
            self._db.flush()
            self._db.execute(
                update(Stock)
                .where(Stock.ticker == ticker)
                .values(data_version=Stock.data_version + 1)
            )
            stmt = update(BacktestResult).values(stale=True)
            if ticker != "0050":
                stmt = stmt.where(BacktestResult.ticker == ticker)
            self._db.execute(stmt)
        return changed

    def import_price_events(self, ticker, rows):
        from app.market_data.repository import MarketDataRepository

        original = self._repository
        self._repository = MarketDataRepository(self._db, commit=False)
        try:
            if self.store_price_events(ticker, rows):
                self._recalculate_adjusted_prices(ticker, validate=True)
        finally:
            self._repository = original
