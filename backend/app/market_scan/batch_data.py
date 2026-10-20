"""Date-first TWSE synchronization, before any per-stock evaluation workers."""

from calendar import monthrange
from collections import defaultdict
from datetime import timedelta
from time import monotonic

from sqlalchemy import select, update

from app.data_source.finmind_client import FinMindClient
from app.data_source.twse_client import TwseBatchClient
from app.market_data.models import Stock, StockDividendEvent, StockPriceDaily
from app.market_data.price_event_sync import sync_market_price_events
from app.market_data.repository import MarketDataRepository
from app.market_data.service import MarketDataService
from app.market_data.validation import is_no_trade, valid_ohlcv
from app.market_scan.data import required_days
from app.market_scan.models import BatchCoverage, DividendCoverage


def event_ranges(days, kind):
    start, end = days[0], days[-1]
    if kind == "scan":
        return [(start, end)]
    ranges = []
    while start <= end:
        stop = min(end, start.replace(day=monthrange(start.year, start.month)[1]))
        ranges.append((start, stop))
        start = stop + timedelta(days=1)
    return ranges


def synchronize(
    factory,
    instruments,
    rules,
    kind,
    dates,
    limiter,
    verify,
    *,
    client=None,
    progress=None,
    mode="full",
):
    client = client or TwseBatchClient()
    started = monotonic()
    counts = dict(mi=0, events=0, finmind=0, price_events=0, tpex=0)
    warnings, errors = [], []
    days = (
        dates[-6:]
        if kind == "scan"
        else [d for d in dates if d >= dates[-1] - timedelta(days=required_days(rules))]
    )
    active = {ticker: listed for ticker, _, listed in instruments}

    def before_finmind():
        verify()
        limiter.acquire()
        counts["finmind"] += 1

    price_complete = True
    if kind == "scan" or mode != "prices":
        verify()
        if progress:
            progress("批次行情 全市場價格事件同步")
        result = sync_market_price_events(
            factory, days[0], days[-1], before_finmind=before_finmind, client=client
        )
        verify()
        price_complete = result.complete
        warnings.extend(result.warnings)
        counts["price_events"] = result.twse_requests
        counts["tpex"] = result.tpex_requests

    if kind == "scan" or mode not in ("prices", "price_events"):
        all_events = set()
        complete = price_complete
        for start, end in event_ranges(days, kind):
            verify()
            if progress:
                progress(f"批次行情 股利事件檢查：{start}～{end}")
            try:
                counts["events"] += 1
                all_events.update(client.events(start, end))
            except Exception as exc:
                complete = False
                warnings.append(f"{start}～{end} 股利事件查詢失敗（{type(exc).__name__}），未重試")
        with factory() as db:
            existing = set(
                db.execute(
                    select(StockDividendEvent.ticker, StockDividendEvent.ex_dividend_date).where(
                        StockDividendEvent.ex_dividend_date.between(days[0], days[-1])
                    )
                ).all()
            )
        missing = defaultdict(list)
        event_details = {(e.ticker, e.day): e for e in all_events}
        for ticker, day in sorted(event_details):
            if ticker in active and active[ticker] <= day and (ticker, day) not in existing:
                missing[ticker].append(day)
        failed = set()
        for index, (ticker, ex_dates) in enumerate(sorted(missing.items()), 1):
            verify()
            if progress:
                progress(f"批次行情 股利補齊 {index}/{len(missing)} 檔：{ticker}")
            try:
                with factory() as db:
                    service = MarketDataService(db, FinMindClient(before_request=before_finmind))
                    # One FinMind request per ticker across all missing months.
                    service.sync_daily_prices(
                        ticker,
                        start_date=min(ex_dates),
                        end_date=max(ex_dates),
                        fetch_prices=False,
                    )
                    found = set(
                        db.scalars(
                            select(StockDividendEvent.ex_dividend_date).where(
                                StockDividendEvent.ticker == ticker,
                                StockDividendEvent.ex_dividend_date.in_(ex_dates),
                            )
                        )
                    )
                    fallback, fallback_warnings = [], []
                    for day in sorted(set(ex_dates) - found):
                        event = event_details[ticker, day]
                        if event.kind == "息" and event.value > 0:
                            fallback.append(
                                dict(
                                    ex_dividend_date=day,
                                    cash_dividend=event.value,
                                    stock_dividend_ratio=0,
                                    cash_capital_increase_ratio=0,
                                    cash_capital_increase_price=0,
                                )
                            )
                            fallback_warnings.append(
                                (ticker, f"{day} FinMind 無配息資料，改用證交所息值 {event.value}")
                            )
                        else:
                            failed.add(ticker)
                            errors.append(
                                (ticker, f"{day} 證交所有除權息事件，但 FinMind 無對應除權息日")
                            )
                    if fallback:
                        db.execute(select(Stock.id).where(Stock.ticker == ticker).with_for_update())
                        service._repository = MarketDataRepository(db, commit=False)
                        service._repository.upsert_dividend_events(ticker, fallback)
                        service._recalculate_adjusted_prices(ticker, validate=True)
                        db.execute(
                            update(Stock)
                            .where(Stock.ticker == ticker)
                            .values(data_version=Stock.data_version + 1)
                        )
                        verify()
                        db.commit()
                        errors.extend(fallback_warnings)
            except Exception as exc:
                failed.add(ticker)
                errors.append((ticker, f"股利補齊失敗（{type(exc).__name__}），未重試"))
        if complete:
            verify()
            with factory() as db:
                previous = {c.ticker: c for c in db.scalars(select(DividendCoverage))}
                for ticker, listed in active.items():
                    if ticker in failed or listed > days[-1]:
                        continue
                    start, end = max(listed, days[0]), days[-1]
                    old = previous.get(ticker)
                    if (
                        old
                        and old.start_date <= end + timedelta(days=1)
                        and old.end_date >= start - timedelta(days=1)
                    ):
                        start, end = min(start, old.start_date), max(end, old.end_date)
                    db.merge(DividendCoverage(ticker=ticker, start_date=start, end_date=end))
                verify()
                db.commit()
        if not complete or failed:
            warnings.append("還原資料未完整：未確認的標的不會列為正常戰法命中，請稍後補齊股利")
    elif mode == "prices":
        warnings.append("本次只下載行情，未補股利；還原資料未完整的標的不會列為正常戰法命中")

    price_days = [] if kind == "initialize" and mode in ("dividends", "price_events") else days
    for index, day in enumerate(price_days):
        verify()
        eligible = {t for t, listed in active.items() if listed <= day}
        if not eligible:
            continue
        with factory() as db:
            bars = list(
                db.scalars(
                    select(StockPriceDaily).where(
                        StockPriceDaily.trade_date == day, StockPriceDaily.ticker.in_(eligible)
                    )
                )
            )
            confirmed = {
                b.ticker
                for b in bars
                if is_no_trade(b) or (valid_ohlcv(b) and valid_ohlcv(b, True))
            }
            coverage = db.get(BatchCoverage, day)
            absent = set(coverage.absent_tickers) if coverage else set()
            # Never let an absence marker hide an invalid existing price row.
            missing = eligible - confirmed - (absent - {b.ticker for b in bars})
        if not missing:
            continue
        if progress:
            progress(f"批次行情 {index + 1}/{len(days)}：{day}")
        try:
            counts["mi"] += 1
            rows, absent, invalid = client.daily(day, eligible)
            errors.extend((t, f"{day} {reason}") for t, reason in invalid.items())
            if kind == "initialize":
                rows = [r for r in rows if r["ticker"] in missing]
            verify()
            with factory() as db:
                try:
                    errors.extend(MarketDataService(db).import_market_day(day, rows))
                    db.merge(BatchCoverage(trade_date=day, absent_tickers=sorted(absent)))
                    verify()
                    db.commit()
                except Exception:
                    db.rollback()
                    raise
        except Exception as exc:
            warnings.append(
                f"{day} 證交所當日行情尚未取得或寫入失敗（{type(exc).__name__}），未重試"
            )
    warnings.append(
        f"批次資料完成：MI_INDEX {counts['mi']} 次、TWT49U {counts['events']} 次、"
        f"TWTAUU {counts['price_events']} 次、TPEx {counts['tpex']} 次、"
        f"FinMind {counts['finmind']} 次，"
        f"耗時 {monotonic() - started:.1f} 秒"
    )
    return warnings, errors
