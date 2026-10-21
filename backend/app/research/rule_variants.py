"""Read-only DB research using production point-in-time signals.

Run with ``python -m app.research.rule_variants --help``. Missing cached data
is reported, never fetched. Returns are fractions. Holding days count exchange
sessions, including suspension days. The top-1% trim removes ceil(n * .01)
trades (so a one-trade group has no trimmed mean).
"""

import argparse
import json
import math
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path
from statistics import mean, median

import numpy as np
from sqlalchemy import select

from app.backtest.data import next_month, taipei_today
from app.backtest.models import BacktestCalendarMonth, BacktestCoverage
from app.backtest.service import restore_rule, rule_snapshot, years_ago
from app.backtest.simulation import adjusted_bars, simulate, usable
from app.conditions.types import ConditionBar
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.market_data.models import StockDividendEvent, StockPriceDaily, StockPriceEvent
from app.market_data.price_adjustment import DividendEvent, PriceEvent
from app.market_scan.models import BatchCoverage, MarketInstrument, ScanCandidate, ScanTask
from app.market_scan.service import chosen_rules
from app.rules.preparation import history_days
from app.trading_costs import TradingCosts
from app.watchlist.models import HoldingsWatchlist


@dataclass(frozen=True)
class Variant:
    name: str
    exit_days: int = 1
    min_slope: float | None = None
    min_turn: float | None = None
    entry: str = "event"
    pullback_pct: float = 0.01
    breakout_lookback: int = 20
    breakout_turnover_mult: float = 2.0
    source: str = "signals"
    conditions: tuple | None = None

    def __post_init__(self):
        if self.source not in ("signals", "engine"):
            raise ValueError("source 必須為 signals 或 engine")
        if self.exit_days < 1:
            raise ValueError("exit_days 必須至少為 1")
        if self.entry not in ("event", "pullback", "breakout"):
            raise ValueError("entry 必須為 event、pullback 或 breakout")
        for field in ("pullback_pct", "breakout_lookback", "breakout_turnover_mult"):
            value = getattr(self, field)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{field} 必須為正數")
        if not isinstance(self.breakout_lookback, int):
            raise ValueError("breakout_lookback 必須為整數")


LEGACY_RULES = {1: [("bollinger_mid_up", {"period": 20}, "premise")]}


VARIANTS = (
    Variant("現行定義", source="engine"),
    Variant("現行定義＋成交金額 ≥ 1,000 萬", source="engine", min_turn=1e7),
    Variant("現行定義＋成交金額 ≥ 1 億", source="engine", min_turn=1e8),
    Variant("原規則"),
    Variant("出場緩衝 2 天", exit_days=2),
    Variant("斜率 ≥ 1%", min_slope=0.01),
    Variant("訊號日成交金額 ≥ 1 億", min_turn=1e8),
    Variant("1+2+3 合併", exit_days=2, min_slope=0.01, min_turn=1e8),
    Variant("出場緩衝 3 天", exit_days=3),
    Variant("斜率 ≥ 0.5%", min_slope=0.005),
    Variant("拉回進場", entry="pullback"),
    Variant("拉回進場＋出場緩衝 2 天", entry="pullback", exit_days=2),
    Variant("放量突破", entry="breakout"),
    Variant("放量突破＋出場緩衝 2 天", entry="breakout", exit_days=2),
)

def _tuning_conditions(*, buffer=0, days=2, rebound=False, slope=False, max_distance=None):
    return (
        ("ma_rising", {"period": 20, "slope_lookback": 5,
                       **({"min_slope_pct": 0.01} if slope else {})}, "premise"),
        ("ma_touch_rebound" if rebound else "price_touch_ma",
         {"period": 20, "tolerance": 0.01,
          **({"max_close_distance_pct": max_distance}
             if rebound and max_distance is not None else {})}, "entry"),
        ("close_below_ma_days", {"period": 20, "days": days,
                                 **({"buffer": buffer} if buffer else {})}, "exit"),
    )


RULE2_TUNING = (
    Variant("現行", source="engine"),
    Variant("A1 出場緩衝 2%", source="engine", conditions=_tuning_conditions(buffer=0.02)),
    Variant("A2 出場連續 3 天", source="engine", conditions=_tuning_conditions(days=3)),
    Variant("B 進場等分歧", source="engine", conditions=_tuning_conditions(rebound=True)),
    Variant("C 斜率 ≥ 1%", source="engine", conditions=_tuning_conditions(slope=True)),
    Variant("A1＋B", source="engine", conditions=_tuning_conditions(buffer=0.02, rebound=True)),
    Variant("A1＋C", source="engine", conditions=_tuning_conditions(buffer=0.02, slope=True)),
    Variant("B＋C", source="engine", conditions=_tuning_conditions(rebound=True, slope=True)),
    Variant("A1＋B＋C", source="engine",
            conditions=_tuning_conditions(buffer=0.02, rebound=True, slope=True)),
)


DISTANCE_VARIANTS = tuple(
    Variant(name, source="engine",
            conditions=_tuning_conditions(buffer=0.02, rebound=True, max_distance=distance))
    for name, distance in (("無限制", None), ("≤ 2%", 0.02), ("≤ 3%", 0.03), ("≤ 5%", 0.05))
)


MARKET_VARIANTS = tuple(
    Variant(name, source="engine", conditions=_tuning_conditions(buffer=0.02, rebound=True))
    for name in ("無濾網", "M1 0050 在 60 日線上", "M2 0050 月線上揚",
                 "M3 過半股票在月線上", "M1＋M3")
)


def select_variants(variant_set, rule_id):
    if variant_set == "distance":
        if rule_id != 1:
            raise ValueError("--variant-set distance 僅支援 rule_id == 1")
        return DISTANCE_VARIANTS
    if variant_set == "market":
        if rule_id != 1:
            raise ValueError("--variant-set market 僅支援 rule_id == 1")
        return MARKET_VARIANTS
    if variant_set == "tuning":
        if rule_id != 1:
            raise ValueError("--variant-set tuning 僅支援 rule_id == 1")
        return RULE2_TUNING
    return VARIANTS


LIQUIDITY_GROUPS = ("≥ 1 億", "1,000 萬～1 億", "< 1,000 萬", "無資料")


class DataUnavailable(ValueError):
    """Cached inputs cannot support a reproducible backtest."""


def load_calendar(db, start, end):
    dates = set()
    month = start.replace(day=1)
    while month <= end:
        key = month.strftime("%Y-%m")
        cached = db.get(BacktestCalendarMonth, key)
        # Closed months must have been checked after month end. For the final
        # partial month, require coverage checked through the requested end.
        required = min(next_month(month), end)
        if cached is None or cached.checked_on < required or not cached.dates:
            raise DataUnavailable(f"交易日曆 {key} 缺漏或尚未確認至 {required}")
        parsed = {date.fromisoformat(d) for d in cached.dates}
        if any(d.strftime("%Y-%m") != key for d in parsed):
            raise DataUnavailable(f"交易日曆 {key} 含其他月份日期")
        dates.update(d for d in parsed if start <= d <= end)
        month = next_month(month)
    if not dates:
        raise DataUnavailable("期間沒有已確認交易日")
    return sorted(dates)


def load_data(db, ticker, start, end, trading_dates, listed_on=None, absent=None):
    """Mirror prepare_data's coverage gate and conversions without sync/write paths.

    Market-scan stocks are confirmed by date (market_scan_batch_coverage), not by
    BacktestCoverage: days before listing or confirmed absent are not gaps.
    """
    expected = {d for d in trading_dates if start <= d <= end}
    bars = list(
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
    present = {b.trade_date for b in bars}
    coverage = db.get(BacktestCoverage, ticker)
    verified = (
        coverage is not None
        and coverage.start_date <= start
        and coverage.end_date >= end
        and {date.fromisoformat(d) for d in coverage.dates if start <= date.fromisoformat(d) <= end}
        <= present
    )
    gaps = {
        d
        for d in expected - present
        if (listed_on is None or d >= listed_on) and ticker not in (absent or {}).get(d, ())
    }
    complete = not gaps and all(
        all(
            getattr(b, field) is not None
            for field in ("adj_open", "adj_high", "adj_low", "adj_close")
        )
        for b in bars
        if b.trade_date in expected
    )
    if not complete and not verified:
        raise DataUnavailable(
            f"行情缺口：缺 {len(gaps)} 個交易日或缺還原欄位，無完整來源確認紀錄"
        )
    raw, turnover = [], {}
    for b in bars:
        if b.trade_date not in expected:
            continue
        values = [float(getattr(b, field)) for field in ("open", "high", "low", "close", "volume")]
        if any(not math.isfinite(v) or v < 0 for v in values):
            raise DataUnavailable(f"{b.trade_date} 行情含負值或無效數字")
        raw.append(ConditionBar(b.trade_date, *values[:4], volume=int(values[4])))
        value = float(b.turnover) if b.turnover is not None else None
        if value is not None and (not math.isfinite(value) or value < 0):
            raise DataUnavailable(f"{b.trade_date} 成交金額無效")
        turnover[b.trade_date.isoformat()] = value
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
    events.extend(
        PriceEvent(e.event_date, float(e.before_close), float(e.reference_price))
        for e in db.scalars(
            select(StockPriceEvent).where(
                StockPriceEvent.ticker == ticker,
                StockPriceEvent.event_date >= start,
                StockPriceEvent.event_date <= end,
            )
        )
    )
    return raw, sorted(events, key=lambda e: e.ex_dividend_date), turnover


def load_benchmark(db, start, end, dates, listed_on=None, absent=None):
    raw, events, _ = load_data(db, "0050", start, end, dates, listed_on, absent)
    valid = [b for b in raw if usable(b)]
    if not valid:
        raise DataUnavailable("0050 無有效歷史行情")
    return {
        b.trade_date.isoformat(): {"open": b.open, "close": b.close}
        for b in adjusted_bars(valid, events)
    }


def indicator(signal, key):
    for condition in signal["conditions"]:
        value = (condition.get("indicators") or {}).get(key)
        if value is not None:
            return value
    return None


def entry_features(prices, turnover, lookback):
    """Point-in-time windows over usable bars, including pre-signal warmup history."""
    ordered = sorted(prices)
    features = {}
    for i, day in enumerate(ordered):
        ma20 = (
            sum(prices[d].close for d in ordered[i - 19:i + 1]) / 20 if i >= 19 else None
        )
        high, average_turnover = None, None
        if i >= lookback:
            previous = ordered[i - lookback:i]
            high = max(prices[d].high for d in previous)
            values = [turnover.get(d) for d in previous]
            if all(value is not None for value in values):
                average_turnover = sum(values) / lookback
        features[day] = (ma20, high, average_turnover)
    return features


def trades_for(
    ticker, signals, prices, turnover, kind, variant, costs, benchmark, dates,
    feature_cache=None,
):
    """Reference state machine: pending fills precede today's close decision."""
    features = {}
    if variant.entry != "event":
        # Cache lifetime is one process_stock call, isolated from other stocks/threads.
        if feature_cache is None:
            feature_cache = {}
        if variant.breakout_lookback not in feature_cache:
            feature_cache[variant.breakout_lookback] = entry_features(
                prices, turnover, variant.breakout_lookback
            )
        features = feature_cache[variant.breakout_lookback]
    indices = {d.isoformat(): i for i, d in enumerate(dates)}
    trades, position, pending, prior, below = [], None, None, False, 0
    signal_day = None
    for signal in signals:
        day = signal["date"]
        if pending:
            if pending == "buy":
                position = day
            else:
                entry, exit = prices[position].open, prices[day].open
                net = costs.net_return(entry, exit, kind if kind in ("stock", "etf") else "stock")
                bo = benchmark.get(position, {}).get("open")
                bx = benchmark.get(day, {}).get("open")
                trades.append(
                    dict(
                        ticker=ticker,
                        variant=variant.name,
                        signal_date=signal_day,
                        entry=position,
                        exit=day,
                        gross=exit / entry - 1,
                        net=net,
                        excess=net - (bx / bo - 1) if bo and bx else None,
                        excess_market=None,
                        excess_random=None,
                        holding_days=indices[day] - indices[position],
                        signal_turnover=turnover.get(signal_day),
                        entry_year=int(position[:4]),
                    )
                )
                position = None
            pending = None
        met = signal["isMet"]
        if position is not None:
            below = 0 if met else below + 1
            if below >= variant.exit_days:
                pending, below = "sell", 0
        elif pending is None and met:
            if variant.entry == "event":
                triggered = not prior
            else:
                ma20, high, average_turnover = features[day]
                bar = prices[day]
                if variant.entry == "pullback":
                    triggered = (
                        ma20 is not None
                        and bar.low <= ma20 * (1 + variant.pullback_pct)
                        and bar.close >= ma20
                    )
                else:
                    turn = turnover.get(day)
                    triggered = (
                        high is not None and average_turnover is not None and turn is not None
                        and turn >= variant.breakout_turnover_mult * average_turnover
                        and bar.close > high
                    )
            if not triggered:
                prior = met
                continue
            ok = True
            if variant.min_slope is not None:
                mid, slope = indicator(signal, "mid"), indicator(signal, "slope")
                ok = bool(mid and slope is not None and slope / mid >= variant.min_slope)
            if variant.min_turn is not None:
                ok = ok and (turnover.get(day) or 0) >= variant.min_turn
            if ok:
                pending, signal_day = "buy", day
        prior = met
    return trades


def engine_trades(ticker, payload, turnover, kind, variant, costs, benchmark):
    """Project official closed fills without replaying engine decisions."""
    trades = []
    for trade in payload["trades"]:
        if trade["status"] != "closed":
            continue
        signal_day = trade["entrySignalDate"]
        turn = turnover.get(signal_day)
        if variant.min_turn is not None and (turn is None or turn < variant.min_turn):
            continue
        entry, exit = trade["entryDate"], trade["exitDate"]
        net = costs.net_return(trade["entryPrice"], trade["exitPrice"], kind)
        bo = benchmark.get(entry, {}).get("open")
        bx = benchmark.get(exit, {}).get("open")
        trades.append(dict(
            ticker=ticker, variant=variant.name, signal_date=signal_day,
            entry=entry, exit=exit, gross=trade["returnRate"], net=net,
            excess=net - (bx / bo - 1) if bo and bx else None,
            excess_market=None, excess_random=None,
            holding_days=trade["holdingDays"], signal_turnover=turn,
            entry_year=int(entry[:4]),
        ))
    return trades


def role_trades(ticker, signals, prices, turnover, kind, costs, benchmark, dates,
                entry_allowed=None, variant_name="無濾網"):
    """Replay daily role signals; filters gate buy orders, never exits or fills."""
    indices = {d.isoformat(): i for i, d in enumerate(dates)}
    trades, position, pending, prior = [], None, None, False
    signal_day = None
    for signal in signals:
        day = signal["date"]
        if pending == "buy":
            position = day
        elif pending == "sell":
            entry = getattr(prices[position], "open", prices[position])
            exit = getattr(prices[day], "open", prices[day])
            trades.extend(engine_trades(
                ticker, {"trades": [dict(
                    status="closed", entrySignalDate=signal_day, entryDate=position,
                    exitDate=day, entryPrice=entry, exitPrice=exit,
                    returnRate=exit / entry - 1,
                    holdingDays=indices[day] - indices[position],
                )]}, turnover, kind, Variant(variant_name, source="engine"), costs, benchmark,
            ))
            position = None
        pending = None
        met = signal["isMet"]
        if position is not None:
            triggered = signal.get("exitTriggered")
            if triggered if triggered is not None else not met:
                pending = "sell"
        else:
            triggered = signal.get("entryTriggered")
            buy = (signal.get("premiseMet") and triggered
                   if triggered is not None else met and not prior)
            if buy and (entry_allowed is None or entry_allowed(day)):
                pending, signal_day = "buy", day
        prior = met
    return trades


def market_filters(benchmark, stock_closes, dates, index_benchmark=None, index_dates=None):
    """Trailing usable-bar means; M2 compares five exchange sessions earlier.

    Future adjustment factors scale every price in a past comparison equally;
    the common end-date basis therefore preserves these inequalities.
    Missing current bars and insufficient history never pass a filter.
    index_benchmark／index_dates: a longer 0050 history for M1/M2, so the 60-day mean
    exists from the first study day instead of blocking early entries for lack of data.
    """
    days = [d.isoformat() for d in dates]
    columns = {day: i for i, day in enumerate(days)}

    def rolling(closes, period):
        ordered = sorted(day for day in closes if day in columns)
        values = np.array([closes[day] for day in ordered], dtype=float)
        if len(values) < period:
            return {}
        means = np.lib.stride_tricks.sliding_window_view(values, period).mean(axis=1)
        return dict(zip(ordered[period - 1:], means, strict=True))

    index_days = [d.isoformat() for d in (index_dates or dates)]
    index_columns = {day: i for i, day in enumerate(index_days)}
    closes = {
        day: bar["close"] for day, bar in (index_benchmark or benchmark).items()
        if day in index_columns
    }
    ordered = sorted(closes)
    values = np.array([closes[day] for day in ordered], dtype=float)

    def index_rolling(period):
        if len(values) < period:
            return {}
        means = np.lib.stride_tricks.sliding_window_view(values, period).mean(axis=1)
        return dict(zip(ordered[period - 1:], means, strict=True))

    ma60, ma20 = index_rolling(60), index_rolling(20)
    m1 = {day: bool(day in ma60 and closes[day] > ma60[day]) for day in days}
    position = {day: i for i, day in enumerate(index_days)}
    m2 = {}
    for day in days:
        i = position.get(day)
        earlier = index_days[i - 5] if i is not None and i >= 5 else None
        m2[day] = bool(earlier and day in ma20 and earlier in ma20 and ma20[day] > ma20[earlier])
    eligible = np.zeros(len(days), dtype=int)
    above = np.zeros(len(days), dtype=int)
    for closes in stock_closes.values():
        averages = rolling(closes, 20)
        positions = np.array([columns[day] for day in averages], dtype=int)
        eligible[positions] += 1
        above[positions] += np.array([closes[day] > avg for day, avg in averages.items()],
                                    dtype=int)
    m3 = {day: bool(eligible[i] and above[i] * 2 > eligible[i])
          for i, day in enumerate(days)}
    return dict(zip((v.name for v in MARKET_VARIANTS),
                    ({day: True for day in days}, m1, m2, m3,
                     {day: m1[day] and m3[day] for day in days}), strict=True))


def entry_allowance(filters, dates, start, end):
    periods = (("2024-07～12", date(2024, 7, 1), date(2024, 12, 31)),
               ("2025", date(2025, 1, 1), date(2025, 12, 31)),
               ("2026", date(2026, 1, 1), date(2026, 12, 31)))
    return {label: {
        name: mean(allowed.get(day.isoformat(), False) for day in selected) if selected else None
        for name, allowed in filters.items()
    } for label, first, last in periods
        for selected in [[d for d in dates if max(first, start) <= d <= min(last, end)]]}


def add_baselines(trades, stock_opens, dates, start, costs, kinds=None, min_stocks=50):
    """Enrich trades without changing fills; dates retain suspended sessions."""
    days = [d.isoformat() for d in dates if d >= start]
    columns = {day: i for i, day in enumerate(days)}
    rows = {ticker: i for i, ticker in enumerate(sorted(stock_opens))}
    opens = np.full((len(rows), len(days)), np.nan)
    for ticker, row in rows.items():
        for day, price in stock_opens[ticker].items():
            if day in columns:
                opens[row, columns[day]] = price
    market_cache, random_pools = {}, {}
    for trade in trades:
        pair = (trade["entry"], trade["exit"])
        if pair not in market_cache:
            baseline = None
            if all(day in columns for day in pair):
                ratios = opens[:, columns[pair[1]]] / opens[:, columns[pair[0]]]
                if np.count_nonzero(~np.isnan(ratios)) >= min_stocks:
                    baseline = costs.net_return(1, float(np.nanmean(ratios)), "stock")
            market_cache[pair] = baseline
        baseline = market_cache[pair]
        trade["excess_market"] = None if baseline is None else trade["net"] - baseline

        ticker, holding = trade["ticker"], trade["holding_days"]
        key = (ticker, holding)
        if key not in random_pools:
            pool = []
            if ticker in rows and 0 < holding < len(days):
                prices = opens[rows[ticker]]
                ratios = prices[holding:] / prices[:-holding]
                kind = (kinds or {}).get(ticker, "stock")
                pool = [
                    costs.net_return(1, float(ratio), kind)
                    for ratio in ratios[~np.isnan(ratios)]
                ]
            random_pools[key] = pool
        pool = random_pools[key]
        rng = random.Random(f"{ticker}|{trade['variant']}|{trade['entry']}")
        samples = rng.sample(pool, 20) if len(pool) > 20 else pool
        trade["excess_random"] = trade["net"] - mean(samples) if samples else None


def liquidity_group(turnover):
    if turnover is None:
        return "無資料"
    return LIQUIDITY_GROUPS[0 if turnover >= 1e8 else 1 if turnover >= 1e7 else 2]


def statistics(trades):
    values = [t["net"] for t in trades]
    excess = [t["excess"] for t in trades if t["excess"] is not None]
    market = [t["excess_market"] for t in trades if t.get("excess_market") is not None]
    randomized = [t["excess_random"] for t in trades if t.get("excess_random") is not None]
    losses = -sum(v for v in values if v < 0)
    trimmed = sorted(values)[: len(values) - math.ceil(len(values) * 0.01)]
    return dict(
        count=len(values),
        win_rate=mean(v > 0 for v in values) if values else None,
        average_net=mean(values) if values else None,
        median_net=median(values) if values else None,
        profit_factor=sum(v for v in values if v > 0) / losses if losses else None,
        no_losses=bool(values) and losses == 0,
        average_excess=mean(excess) if excess else None,
        positive_excess_rate=mean(v > 0 for v in excess) if excess else None,
        excess_count=len(excess),
        average_excess_market=mean(market) if market else None,
        positive_excess_market_rate=mean(v > 0 for v in market) if market else None,
        average_excess_random=mean(randomized) if randomized else None,
        positive_excess_random_rate=mean(v > 0 for v in randomized) if randomized else None,
        holding_le_10_rate=mean(t["holding_days"] <= 10 for t in trades) if trades else None,
        holding_gt_20_rate=mean(t["holding_days"] > 20 for t in trades) if trades else None,
        median_holding_days=median(t["holding_days"] for t in trades) if trades else None,
        trimmed_average_net=mean(trimmed) if trimmed else None,
        trimmed_count=len(values) - len(trimmed),
        stock_count=len({t["ticker"] for t in trades}),
    )


def summarize(trades, start, end, variants=VARIANTS):
    groups = [("全部", trades)]
    groups.extend(
        (
            f"成交金額：{label}",
            [t for t in trades if liquidity_group(t["signal_turnover"]) == label],
        )
        for label in LIQUIDITY_GROUPS
    )
    # The requested 2023–2024 first bucket generalizes to other CLI date ranges.
    if start.year <= 2024:
        groups.append(
            (
                f"進場期間：{start:%Y-%m}～{min(end, date(2024, 12, 31)):%Y-%m}",
                [t for t in trades if t["entry_year"] <= 2024],
            )
        )
    groups.extend(
        (f"進場年份：{year}", [t for t in trades if t["entry_year"] == year])
        for year in range(max(2025, start.year), end.year + 1)
    )
    return {
        label: {v.name: statistics([t for t in rows if t["variant"] == v.name]) for v in variants}
        for label, rows in groups
    }


def markdown(result):
    lines = ["<!-- 結論待填 -->"] * 3
    params = result["parameters"]
    lines += [
        "",
        f"股票池：{params['universe']}，共 {result['universe_size']} 檔；"
        f"成功 {result['succeeded']} 檔，跳過 {len(result['skipped'])} 檔。",
        f"期間：{params['start']}～{params['end']}；戰法 {params['rule_id']}。",
        "",
        "成交金額依訊號日分組；持有天數依交易日曆計算。期末未平倉不計。",
        "拉回進場＝戰法二成立且當日最低價在月線上方 1% 內、收盤不破月線；"
        "放量突破＝戰法二成立且成交金額 ≥ 前 20 日均的 2 倍、"
        "收盤突破前 20 日最高價。皆為隔日開盤進場。",
        "超額統計僅計算有 0050 同日開盤資料的交易，分母為超額樣本數。",
        "全市場＝同期間全部股票等權平均；同股隨機＝同一股票隨機進場、"
        "持有相同交易日數，各 20 次平均。皆已扣成本。",
        "去頂端 1% 使用淨報酬排序，移除筆數向上取整；單筆組移除後為無資料。",
        "獲利因子無虧損時顯示無虧損；其他無法計算值顯示 —。",
    ]
    lines.append(
        "現行定義＝DB 中的戰法定義，交易由正式回測引擎產生（與網頁回測、全市場掃描一致）。"
    )
    if params.get("variant_set") == "market":
        lines = [line for line in lines
                 if not line.startswith(("拉回進場＝", "現行定義＝"))]
        lines += [
            "市場濾網使用 A1＋B：ma_rising(20, 5)、ma_touch_rebound(20, 0.01)、"
            "close_below_ma_days(20, 2, buffer=0.02)。只限制訊號日進場，不影響出場。",
            "M1：0050 收盤 > 60 日均線；M2：0050 月線 > 5 個交易日前月線；"
            "M3：股票池當日有效且滿 20 根的股票，收盤 > 月線比例 > 50%。",
            "", "## 允許進場比例", "",
            "分母為研究期間內各段交易日；資料不足日不允許進場，無交易日顯示 —。",
            "", "| 濾網 | 2024-07～12 | 2025 | 2026 |", "|---|---:|---:|---:|",
        ]
        for variant in MARKET_VARIANTS:
            cells = [variant.name]
            for period in ("2024-07～12", "2025", "2026"):
                value = result["entry_allowance"][period][variant.name]
                cells.append("—" if value is None else f"{value:.1%}")
            lines.append("| " + " | ".join(cells) + " |")
    elif params.get("variant_set") in ("tuning", "distance"):
        lines.append("")
        # Each line records the complete replacement, including unchanged roles.
        for variant in params["variants"]:
            conditions = variant["conditions"]
            if conditions is None:
                definition = "DB 戰法條件：" + json.dumps(
                    params["rule"]["conditions"], ensure_ascii=False, sort_keys=True)
            else:
                definition = "；".join(
                    f"{role}: {cid} {json.dumps(values, sort_keys=True)}"
                    for cid, values, role in conditions
                )
            lines.append(f"- {variant['name']}：{definition}")
        lines = [line for line in lines if not line.startswith("拉回進場＝")]
    elif params["rule_id"] in LEGACY_RULES:
        lines.append("其餘變體以舊戰法二（bollinger_mid_up）的每日判斷重算，作為對照。")
    if result["benchmark_reason"]:
        lines += ["", f"0050 基準不可用：{result['benchmark_reason']}"]
    for group, variants in result["statistics"].items():
        lines += [
            "",
            f"## {group}",
            "",
            "| 變體 | 筆數 | 淨勝率 | 平均淨報酬 | 中位淨報酬 | 獲利因子 | 平均超額 |"
            " 超額正比例 | 超額樣本 | 平均超額（全市場） | 超額為正比例（全市場） |"
            " 平均超額（同股隨機） | 超額為正比例（同股隨機） |"
            " 持有日中位數 | 持有 ≤ 10 天比例 | 持有 > 20 天比例 | 去頂端 1% 平均淨 | 股票數 |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for name, s in variants.items():

            def pct(key, stats=s):
                return "—" if stats[key] is None else f"{stats[key]:.1%}"

            factor = (
                f"{s['profit_factor']:.2f}"
                if s["profit_factor"] is not None
                else "無虧損"
                if s["no_losses"]
                else "—"
            )
            holding = "—" if s["median_holding_days"] is None else f"{s['median_holding_days']:g}"
            cells = [
                name,
                str(s["count"]),
                pct("win_rate"),
                pct("average_net"),
                pct("median_net"),
                factor,
                pct("average_excess"),
                pct("positive_excess_rate"),
                str(s["excess_count"]),
                pct("average_excess_market"),
                pct("positive_excess_market_rate"),
                pct("average_excess_random"),
                pct("positive_excess_random_rate"),
                holding,
                pct("holding_le_10_rate"),
                pct("holding_gt_20_rate"),
                pct("trimmed_average_net"),
                str(s["stock_count"]),
            ]
            lines.append("| " + " | ".join(cells) + " |")
    if result["skipped"]:
        lines += ["", "## 跳過清單", ""]
        lines.extend(f"- {s['ticker']}：{s['reason']}" for s in result["skipped"])
    return "\n".join(lines) + "\n"


def load_universe(db, universe):
    if universe == "market":
        query = select(MarketInstrument.ticker).where(MarketInstrument.active.is_(True))
    elif universe == "watchlist":
        query = select(HoldingsWatchlist.ticker).where(HoldingsWatchlist.is_active.is_(True))
    else:
        task = db.get(ScanTask, "scan")
        if task is None:
            raise DataUnavailable("找不到最新 scan batch")
        query = select(ScanCandidate.ticker).where(
            ScanCandidate.batch_id == task.batch_id, ScanCandidate.status == "normal"
        )
    return sorted(set(db.scalars(query)))


def process_stock(
    factory,
    ticker,
    rule,
    start,
    end,
    warm,
    dates,
    kind,
    costs,
    benchmark,
    listed_on=None,
    absent=None,
    variants=VARIANTS,
):
    started = time.perf_counter()
    closes = {}
    try:
        with factory() as db:
            raw, events, turnover = load_data(db, ticker, warm, end, dates, listed_on, absent)
        if variants == MARKET_VARIANTS:
            prices = {b.trade_date.isoformat(): b
                      for b in adjusted_bars([b for b in raw if usable(b)], events)}
            closes = {day: b.close for day, b in prices.items()}
            if getattr(rule, "evaluation_frequency", "daily") != "daily":
                raise ValueError("market 重播僅支援 daily 戰法")
            replacement = rule_snapshot(rule)
            replacement["conditions"] = [
                dict(condition_id=cid, params=values.copy(), role=role, sort_order=i)
                for i, (cid, values, role) in enumerate(MARKET_VARIANTS[0].conditions)
            ]
            payload = simulate(restore_rule(replacement), ticker, raw, events, start, end, dates)
            fields = ("date", "isMet", "premiseMet", "entryTriggered", "exitTriggered")
            return dict(
                ticker=ticker, trades=[], reason=None,
                signals=[{key: signal[key] for key in fields} for signal in payload["signals"]],
                opens={day: b.open for day, b in prices.items()}, closes=closes,
                turnover={s["date"]: turnover.get(s["date"]) for s in payload["signals"]},
                elapsed_seconds=time.perf_counter() - started,
                actual_start=payload["actualStart"], actual_end=payload["actualEnd"],
            )
        payload = simulate(rule, ticker, raw, events, start, end, dates)
        signals = payload["signals"]
        if rule.id in LEGACY_RULES and any(v.source == "signals" for v in variants):
            legacy = rule_snapshot(rule)
            legacy["logic_operator"] = "AND"
            legacy["conditions"] = [
                dict(condition_id=condition, params=params.copy(), role=role, sort_order=i)
                for i, (condition, params, role) in enumerate(LEGACY_RULES[rule.id])
            ]
            signals = simulate(
                restore_rule(legacy), ticker, raw, events, start, end, dates
            )["signals"]
        prices = {
            b.trade_date.isoformat(): b
            for b in adjusted_bars([b for b in raw if usable(b)], events)
        }
        trades = []
        feature_cache = {}
        payloads = {None: payload}
        for variant in variants:
            if variant.source == "engine":
                key = (json.dumps(variant.conditions, sort_keys=True)
                       if variant.conditions is not None else None)
                if key not in payloads:
                    replacement = rule_snapshot(rule)
                    replacement["conditions"] = [
                        dict(condition_id=cid, params=values.copy(), role=role, sort_order=i)
                        for i, (cid, values, role) in enumerate(variant.conditions)
                    ]
                    payloads[key] = simulate(
                        restore_rule(replacement), ticker, raw, events, start, end, dates)

                trades.extend(engine_trades(
                    ticker, payloads[key], turnover, kind, variant, costs, benchmark,
                ))
                continue
            trades.extend(
                trades_for(
                    ticker,
                    signals,
                    prices,
                    turnover,
                    kind,
                    variant,
                    costs,
                    benchmark,
                    dates,
                    feature_cache,
                )
            )
        return dict(
            ticker=ticker,
            trades=trades,
            opens={day: b.open for day, b in prices.items()},
            reason=None,
            elapsed_seconds=time.perf_counter() - started,
            actual_start=payload["actualStart"],
            actual_end=payload["actualEnd"],
        )
    except Exception as exc:
        return dict(
            ticker=ticker,
            trades=[],
            **({"closes": closes} if variants == MARKET_VARIANTS else {}),
            reason=f"{type(exc).__name__}: {exc}",
            elapsed_seconds=time.perf_counter() - started,
        )


def run_research(args, factory=SessionLocal):
    started = time.perf_counter()
    variant_set = getattr(args, "variant_set", "all")
    variants = select_variants(variant_set, args.rule_id)
    # --start overrides --years when the DB history is shorter than the default window.
    start = getattr(args, "start", None) or years_ago(args.end, args.years)
    costs = TradingCosts.from_settings(get_settings())
    with factory() as db:
        tickers = load_universe(db, args.universe)
        rule = restore_rule(rule_snapshot(chosen_rules(db, [args.rule_id])[0]))
        kinds = dict(db.execute(select(MarketInstrument.ticker, MarketInstrument.kind)).all())
        listed = dict(db.execute(select(MarketInstrument.ticker, MarketInstrument.listed_on)).all())
        absent = {c.trade_date: set(c.absent_tickers) for c in db.scalars(select(BatchCoverage))}
        # history_days is a conservative cross-rule default (276 days for rule 1); a shorter
        # --warm-days is valid when it still covers the rule's indicator lookback.
        warm = start - timedelta(days=getattr(args, "warm_days", None) or history_days(rule))
        calendar_reason = None
        try:
            dates = load_calendar(db, warm, args.end)
        except DataUnavailable as exc:
            dates, calendar_reason = [], str(exc)
        benchmark, benchmark_reason = {}, calendar_reason
        if not calendar_reason:
            try:
                benchmark = load_benchmark(
                    db, warm, args.end, dates, listed.get("0050"), absent
                )
            except Exception as exc:
                benchmark_reason = f"{type(exc).__name__}: {exc}"
        index_benchmark, index_dates = None, None
        if variant_set == "market" and not calendar_reason:
            # 0050 history before the study warm-up, so M1's 60-day mean exists on day one.
            index_start = start - timedelta(days=150)
            index_dates = load_calendar(db, index_start, args.end)
            index_benchmark = load_benchmark(
                db, index_start, args.end, index_dates, listed.get("0050"), absent
            )
    results = []
    if calendar_reason:
        results = [
            dict(ticker=t, trades=[], reason=calendar_reason, elapsed_seconds=0) for t in tickers
        ]
    else:
        # simulate uses indices[end] for open positions. End can be a weekend;
        # the final confirmed session is the effective end, while parameters
        # retain the user's requested date.
        effective_end = dates[-1]
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = [
                executor.submit(
                    process_stock,
                    factory,
                    ticker,
                    rule,
                    start,
                    effective_end,
                    warm,
                    dates,
                    kinds.get(ticker),
                    costs,
                    benchmark,
                    listed.get(ticker),
                    absent,
                    variants,
                )
                for ticker in tickers
            ]
            for future in as_completed(futures):
                results.append(future.result())
                if len(results) % 50 == 0 or len(results) == len(tickers):
                    print(
                        f"完成 {len(results)}/{len(tickers)} 檔，"
                        f"耗時 {time.perf_counter() - started:.1f} 秒",
                        file=sys.stderr,
                    )
    results.sort(key=lambda r: r["ticker"])
    market_extra = {}
    if variant_set == "market":
        filters = market_filters(
            benchmark, {r["ticker"]: r.get("closes", {}) for r in results}, dates,
            index_benchmark, index_dates,
        )
        market_extra["entry_allowance"] = entry_allowance(filters, dates, start, args.end)
        for result in results:
            if result["reason"] is None:
                for variant in variants:
                    result["trades"].extend(role_trades(
                        result["ticker"], result["signals"], result["opens"], result["turnover"],
                        kinds.get(result["ticker"]) or "stock", costs, benchmark, dates,
                        entry_allowed=filters[variant.name].get, variant_name=variant.name,
                    ))
    trades = [t for r in results for t in r["trades"]]
    add_baselines(
        trades,
        {r["ticker"]: r["opens"] for r in results if r["reason"] is None},
        dates,
        start,
        costs,
        kinds,
    )
    return dict(
        **market_extra,
        parameters=dict(
            universe=args.universe,
            rule_id=args.rule_id,
            start=start.isoformat(),
            end=args.end.isoformat(),
            years=args.years,
            workers=args.workers,
            warm_start=warm.isoformat(),
            rule=rule_snapshot(rule),
            costs=costs.snapshot(),
            variant_set=variant_set,
            variants=[asdict(v) for v in variants],
        ),
        universe_size=len(tickers),
        succeeded=sum(r["reason"] is None for r in results),
        skipped=[dict(ticker=r["ticker"], reason=r["reason"]) for r in results if r["reason"]],
        benchmark_reason=benchmark_reason,
        trades=trades,
        stocks=[{k: v for k, v in r.items()
                 if k not in ("trades", "opens", "closes", "signals", "turnover")}
                for r in results],
        statistics=summarize(trades, start, args.end, variants),
        elapsed_seconds=time.perf_counter() - started,
    )


def positive_int(value):
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("必須為正整數")
    return parsed


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--universe", required=True, choices=("market", "watchlist", "candidates"))
    parser.add_argument(
        "--variant-set", choices=("all", "tuning", "market", "distance"), default="all"
    )
    parser.add_argument("--rule-id", type=positive_int, default=1)
    parser.add_argument(
        "--end", type=date.fromisoformat, default=taipei_today() - timedelta(days=1)
    )
    parser.add_argument("--years", type=positive_int, default=3)
    parser.add_argument("--start", type=date.fromisoformat, default=None)
    parser.add_argument("--warm-days", type=positive_int, default=None)
    parser.add_argument("--workers", type=positive_int, default=4)
    parser.add_argument("--out-json", type=Path, required=True)
    parser.add_argument("--out-md", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.variant_set in ("tuning", "market", "distance") and args.rule_id != 1:
        parser.error(f"--variant-set {args.variant_set} 僅支援 rule_id == 1")
    if args.out_json.resolve() == args.out_md.resolve():
        parser.error("JSON 與 Markdown 路徑不可相同")
    result = run_research(args)
    args.out_json.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8"
    )
    args.out_md.write_text(markdown(result), encoding="utf-8")


if __name__ == "__main__":
    main()
