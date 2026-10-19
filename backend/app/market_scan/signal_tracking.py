"""Immutable first signals and DB-only, bounded return backfill."""

from collections import defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy import select

from app.backtest.models import BacktestCalendarMonth
from app.core.config import get_settings
from app.market_data.models import StockPriceDaily
from app.market_data.validation import valid_ohlcv
from app.market_scan.models import MarketInstrument, SignalHistory, SignalReturn
from app.trading_costs import TradingCosts


def record_signals(db, batch_id, outcomes, metadata):
    """Caller owns publication transaction. Never delete or revise first snapshots."""
    day = date.fromisoformat(metadata["baseline"])
    existing = {
        (s.ticker, s.rule_id): s
        for s in db.scalars(select(SignalHistory).where(SignalHistory.signal_date == day))
    }
    settings = get_settings()
    costs = TradingCosts.from_settings(settings).snapshot()
    now = datetime.utcnow()
    for outcome in outcomes:
        for row in outcome.candidates:
            if row["status"] != "normal":
                continue
            key = row["ticker"], row["rule_id"]
            signal = existing.get(key)
            if signal:
                signal.last_batch_id, signal.last_seen_at = batch_id, now
                continue
            signal = SignalHistory(
                signal_date=day,
                **{
                    k: row[k]
                    for k in (
                        "ticker",
                        "stock_name",
                        "rule_id",
                        "rule_name",
                        "kind",
                        "price_date",
                        "older_quote",
                        "close",
                        "volume",
                        "turnover",
                        "indicators",
                    )
                },
                source=metadata["source"],
                first_batch_id=batch_id,
                last_batch_id=batch_id,
                created_at=now,
                last_seen_at=now,
                cost_snapshot=costs,
            )
            db.add(signal)
            db.flush()
            existing[key] = signal
            db.add_all(
                [
                    SignalReturn(signal_id=signal.id, horizon=n, status="pending", values_json={})
                    for n in settings.tracking_horizons
                ]
            )


def valid(bar):
    return bar.volume > 0 and valid_ohlcv(bar) and valid_ohlcv(bar, True)


def calculate(signal, horizon, bars, benchmark, dates, active):
    """Horizon N exits N market sessions after entry; horizon 1 is next-session close."""
    available = [
        b for b in bars if b.trade_date > signal.signal_date and b.trade_date in dates and valid(b)
    ]
    if not available:
        return (
            ("pending", "等待下一有效交易日進場", {})
            if active
            else ("unavailable", "標的已不在有效上市名單，無可用進場行情", {})
        )
    entry = available[0]
    index = dates.index(entry.trade_date) + horizon
    if index >= len(dates):
        return "pending", "觀察期尚未到期", {}
    due = dates[index]
    if not active:
        return "unavailable", "標的已不在有效上市名單，無法確認完整觀察期", {}
    period = [b for b in available if b.trade_date <= due]
    exit_bar = period[-1]
    price, exit_price = float(entry.adj_open), float(exit_bar.adj_close)
    base_entry, base_exit = benchmark.get(entry.trade_date), benchmark.get(due)
    if not base_entry or not base_exit or not valid(base_entry) or not valid(base_exit):
        return "unavailable", "0050 進場日或到期日行情不足", {}
    gross = exit_price / price - 1
    net = TradingCosts.from_snapshot(signal.cost_snapshot).net_return(
        price, exit_price, signal.kind
    )
    base = float(base_exit.adj_close) / float(base_entry.adj_open) - 1
    return (
        "completed",
        None,
        dict(
            entryDate=entry.trade_date.isoformat(),
            entryPrice=price,
            dueDate=due.isoformat(),
            valuationDate=exit_bar.trade_date.isoformat(),
            exitPrice=exit_price,
            grossReturn=gross,
            netReturn=net,
            benchmarkReturn=base,
            excessReturn=net - base,
            maxAdverseReturn=min(float(b.adj_low) for b in period) / price - 1,
        ),
    )


def backfill(factory, as_of, verify=lambda: None):
    """Keyset pages; each page bulk-loads dates, instruments, returns and OHLC, no HTTP."""
    cursor = 0
    while True:
        verify()
        with factory() as db:
            signals = list(
                db.scalars(
                    select(SignalHistory)
                    .where(
                        SignalHistory.id > cursor,
                        SignalHistory.signal_date < as_of,
                        SignalHistory.id.in_(
                            select(SignalReturn.signal_id).where(SignalReturn.status != "completed")
                        ),
                    )
                    .order_by(SignalHistory.id)
                    .limit(200)
                )
            )
            if not signals:
                return
            cursor = signals[-1].id
            start = min(s.signal_date for s in signals)
            months = list(
                db.scalars(
                    select(BacktestCalendarMonth).where(
                        BacktestCalendarMonth.month.between(
                            start.strftime("%Y-%m"), as_of.strftime("%Y-%m")
                        )
                    )
                )
            )
            calendar = {m.month: m for m in months}
            probe = start.replace(day=1)
            complete = True
            while probe <= as_of:
                m = calendar.get(probe.strftime("%Y-%m"))
                next_month = (probe.replace(day=28) + timedelta(days=4)).replace(day=1)
                if m is None or m.checked_on < min(next_month, as_of):
                    complete = False
                probe = next_month
            dates = sorted(
                {
                    date.fromisoformat(d)
                    for m in months
                    for d in m.dates
                    if start.isoformat() < d <= as_of.isoformat()
                }
            )
            tickers = {s.ticker for s in signals} | {"0050"}
            by_ticker = defaultdict(list)
            for bar in db.scalars(
                select(StockPriceDaily)
                .where(
                    StockPriceDaily.ticker.in_(tickers),
                    StockPriceDaily.trade_date > start,
                    StockPriceDaily.trade_date <= as_of,
                )
                .order_by(StockPriceDaily.trade_date)
            ):
                by_ticker[bar.ticker].append(bar)
            benchmark = {b.trade_date: b for b in by_ticker["0050"]}
            active = set(
                db.scalars(
                    select(MarketInstrument.ticker).where(
                        MarketInstrument.ticker.in_(tickers), MarketInstrument.active.is_(True)
                    )
                )
            )
            returns = list(
                db.scalars(
                    select(SignalReturn).where(
                        SignalReturn.signal_id.in_([s.id for s in signals]),
                        SignalReturn.status != "completed",
                    )
                )
            )
            lookup = {s.id: s for s in signals}
            for result in returns:
                signal = lookup[result.signal_id]
                result.status, result.reason, result.values_json = calculate(
                    signal,
                    result.horizon,
                    by_ticker[signal.ticker],
                    benchmark,
                    dates,
                    signal.ticker in active,
                )
                if not complete and result.status != "pending":
                    result.status, result.reason, result.values_json = (
                        "unavailable",
                        "交易日曆不完整",
                        {},
                    )
            verify()
            db.commit()
