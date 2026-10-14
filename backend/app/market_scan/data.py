"""Range-aware history initialization and bounded incremental sync; no strategy logic."""

from datetime import date, timedelta

from sqlalchemy import select

from app.data_source.finmind_client import FinMindClient
from app.market_data.models import StockPriceDaily
from app.market_data.service import MarketDataService
from app.market_data.validation import valid_ohlcv
from app.market_scan.models import ScanCoverage
from app.rules.preparation import history_days


def required_days(rules):
    # Shared history budget already includes three months of monthly warm-up.
    return max((history_days(rule) for rule in rules), default=365)


def load_bars(db, ticker, start, end):
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


def group_missing(days, missing):
    groups = []
    for i, needed in enumerate(missing):
        if needed:
            if i == 0 or not missing[i - 1]:
                groups.append([days[i], days[i]])
            else:
                groups[-1][1] = days[i]
    return groups


def missing_ranges(days, bars, coverage):
    present = {b.trade_date: b for b in bars}
    missing = []
    for day in days:
        iso = day.isoformat()
        bar = present.get(day)
        valid = bar is not None and valid_ohlcv(bar) and valid_ohlcv(bar, adjusted=True)
        confirmed_absent = bar is None and any(
            r["start"] <= iso <= r["end"] and iso not in r["dates"] for r in coverage
        )
        missing.append(not (valid or confirmed_absent))
    return group_missing(days, missing)


def sync_ranges(db, ticker, days, limiter):
    if not days:
        return
    coverage = db.get(ScanCoverage, ticker)
    ranges = list(coverage.ranges) if coverage else []
    bars = load_bars(db, ticker, days[0], days[-1])
    gaps = missing_ranges(days, bars, ranges)
    service = MarketDataService(db, client=FinMindClient(before_request=limiter.acquire))

    def record(start, end):
        nonlocal ranges
        returned = load_bars(db, ticker, start, end)
        ranges.append(
            dict(
                start=start.isoformat(),
                end=end.isoformat(),
                dates=[
                    b.trade_date.isoformat()
                    for b in returned
                    if valid_ohlcv(b) and valid_ohlcv(b, True)
                ],
            )
        )
        merged = []
        for r in sorted(ranges, key=lambda r: r["start"]):
            if merged and date.fromisoformat(r["start"]) <= date.fromisoformat(
                merged[-1]["end"]
            ) + timedelta(days=1):
                merged[-1]["end"] = max(merged[-1]["end"], r["end"])
                merged[-1]["dates"] = sorted(set(merged[-1]["dates"]) | set(r["dates"]))
            else:
                merged.append(dict(r))
        ranges = merged
        db.merge(ScanCoverage(ticker=ticker, ranges=ranges))
        db.commit()

    for start, end in gaps:
        service.sync_daily_prices(ticker, start_date=start, end_date=end)
        record(start, end)
    # Existing shared prices are reused. Verify dividend coverage separately without
    # downloading complete OHLC ranges again on the first stage-three initialization.
    missing_events = [
        not any(r["start"] <= d.isoformat() <= r["end"] for r in ranges) for d in days
    ]
    for start, end in group_missing(days, missing_events):
        service.sync_daily_prices(ticker, start_date=start, end_date=end, fetch_prices=False)
        record(start, end)


def prepare(db, ticker, listed_on, kind, rules, dates, limiter):
    baseline = dates[-1]
    start = max(listed_on, baseline - timedelta(days=required_days(rules)))
    requested = [d for d in dates if d >= start]
    if kind == "scan":
        # Only the baseline and previous five sessions; never fill historical lookback here.
        requested = [d for d in dates[-6:] if d >= listed_on]
    sync_ranges(db, ticker, requested, limiter)
    return load_bars(db, ticker, start, baseline)
