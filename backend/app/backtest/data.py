"""DB-first preparation, exchange sessions and source-confirmed coverage."""

import math
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select

from app.backtest.models import BacktestCalendarMonth, BacktestCoverage
from app.conditions.types import ConditionBar
from app.data_source import twse_client
from app.market_data.models import StockDividendEvent, StockPriceDaily
from app.market_data.price_adjustment import DividendEvent
from app.market_data.service import MarketDataService


def taipei_today():
    return datetime.now(ZoneInfo("Asia/Taipei")).date()


def next_month(day):
    return (day.replace(day=28) + timedelta(days=4)).replace(day=1)


def load_trading_dates(
    session_factory, start: date, end: date, *, allow_empty_current_month=False
) -> list[date]:
    """Cache completed months; refresh an open month when its date coverage is stale."""
    month, dates, today = start.replace(day=1), set(), taipei_today()
    with session_factory() as db, httpx.Client(timeout=20) as client:
        while month <= end:
            key = month.strftime("%Y-%m")
            cached = db.get(BacktestCalendarMonth, key)
            if cached is None or (
                cached.checked_on < next_month(month)
                and (
                    cached.checked_on != today
                    or (
                        month == end.replace(day=1)
                        and (not cached.dates or max(cached.dates) < end.isoformat())
                    )
                )
            ):
                response = twse_client.get(
                    "https://www.twse.com.tw/exchangeReport/FMTQIK",
                    client=client,
                    params={"response": "json", "date": month.strftime("%Y%m%d")},
                    timeout=20,
                )
                response.raise_for_status()
                payload = response.json()
                empty_current = (
                    allow_empty_current_month
                    and month == today.replace(day=1)
                    and payload.get("stat") == "很抱歉，沒有符合條件的資料!"
                )
                if not empty_current and (payload.get("stat") != "OK" or not payload.get("data")):
                    raise ValueError(f"證交所 {key} 交易日期無法確認，未開始股票回測")
                parsed = []
                for row in payload.get("data", []):
                    y, m, d = map(int, row[0].split("/"))
                    day = date(y + 1911, m, d)
                    if day.strftime("%Y-%m") != key:
                        raise ValueError("交易日來源回傳月份不符")
                    parsed.append(day.isoformat())
                cached = BacktestCalendarMonth(month=key, checked_on=today, dates=parsed)
                db.merge(cached)
                db.commit()
            dates.update(date.fromisoformat(value) for value in cached.dates)
            month = next_month(month)
    return sorted(day for day in dates if start <= day <= end)


def prepare_data(db, ticker, start, end, trading_dates):
    expected = {day for day in trading_dates if start <= day <= end}

    def read_bars():
        return list(
            db.scalars(
                select(StockPriceDaily)
                .where(
                    StockPriceDaily.ticker == ticker,
                    StockPriceDaily.trade_date >= start,
                    StockPriceDaily.trade_date <= end,
                )
                .order_by(StockPriceDaily.trade_date)
            )
        )

    bars = read_bars()
    present = {bar.trade_date for bar in bars}
    coverage = db.get(BacktestCoverage, ticker)
    # A previous successful fetch establishes that pre-listing/suspended dates
    # were genuinely unavailable. If any previously returned row disappears, refetch.
    verified = (
        coverage is not None
        and coverage.start_date <= start
        and coverage.end_date >= end
        and {date.fromisoformat(d) for d in coverage.dates if start <= date.fromisoformat(d) <= end}
        <= present
    )
    complete = expected <= present and all(
        all(
            getattr(b, name) is not None
            for name in ("adj_open", "adj_high", "adj_low", "adj_close")
        )
        for b in bars
        if b.trade_date in expected
    )
    if not complete and not verified:
        days = max(1, (taipei_today() - start).days + 1)
        if MarketDataService(db).sync_daily_prices(ticker, days=days) == 0:
            raise ValueError("FinMind 未回傳歷史資料")
        bars = read_bars()
        db.merge(
            BacktestCoverage(
                ticker=ticker,
                start_date=start,
                end_date=end,
                dates=[b.trade_date.isoformat() for b in bars],
            )
        )
        db.commit()
    # Reject corrupt numbers; zero OHLC / zero volume sessions remain non-tradable.
    raw = []
    for b in bars:
        if b.trade_date not in expected:
            continue  # Exclude old synthetic weekend/holiday seed rows.
        values = [float(getattr(b, key)) for key in ("open", "high", "low", "close", "volume")]
        if any(not math.isfinite(v) or v < 0 for v in values):
            raise ValueError(f"{b.trade_date} 行情含負值或無效數字")
        raw.append(ConditionBar(b.trade_date, *values[:4], volume=int(values[4])))
    events = [
        DividendEvent(
            ex_dividend_date=e.ex_dividend_date,
            cash_dividend=float(e.cash_dividend),
            stock_dividend_ratio=float(e.stock_dividend_ratio),
            cash_capital_increase_ratio=float(e.cash_capital_increase_ratio),
            cash_capital_increase_price=float(e.cash_capital_increase_price),
        )
        for e in db.scalars(
            select(StockDividendEvent).where(
                StockDividendEvent.ticker == ticker,
                StockDividendEvent.ex_dividend_date >= start,
                StockDividendEvent.ex_dividend_date <= end,
            )
        )
    ]
    return raw, events
