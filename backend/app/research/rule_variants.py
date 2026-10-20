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

    def __post_init__(self):
        if self.exit_days < 1:
            raise ValueError("exit_days 必須至少為 1")


VARIANTS = (
    Variant("原規則"),
    Variant("出場緩衝 2 天", exit_days=2),
    Variant("斜率 ≥ 1%", min_slope=0.01),
    Variant("訊號日成交金額 ≥ 1 億", min_turn=1e8),
    Variant("1+2+3 合併", exit_days=2, min_slope=0.01, min_turn=1e8),
    Variant("出場緩衝 3 天", exit_days=3),
    Variant("斜率 ≥ 0.5%", min_slope=0.005),
)
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


def load_benchmark(db, start, end, dates):
    raw, events, _ = load_data(db, "0050", start, end, dates)
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


def trades_for(ticker, signals, prices, turnover, kind, variant, costs, benchmark, dates):
    """Reference state machine: pending fills precede today's close decision."""
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
        elif met and not prior:
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
        median_holding_days=median(t["holding_days"] for t in trades) if trades else None,
        trimmed_average_net=mean(trimmed) if trimmed else None,
        trimmed_count=len(values) - len(trimmed),
        stock_count=len({t["ticker"] for t in trades}),
    )


def summarize(trades, start, end):
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
        label: {v.name: statistics([t for t in rows if t["variant"] == v.name]) for v in VARIANTS}
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
        "超額統計僅計算有 0050 同日開盤資料的交易，分母為超額樣本數。",
        "全市場＝同期間全部股票等權平均；同股隨機＝同一股票隨機進場、"
        "持有相同交易日數，各 20 次平均。皆已扣成本。",
        "去頂端 1% 使用淨報酬排序，移除筆數向上取整；單筆組移除後為無資料。",
        "獲利因子無虧損時顯示無虧損；其他無法計算值顯示 —。",
    ]
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
            " 持有日中位數 | 去頂端 1% 平均淨 | 股票數 |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
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
):
    started = time.perf_counter()
    try:
        with factory() as db:
            raw, events, turnover = load_data(db, ticker, warm, end, dates, listed_on, absent)
        payload = simulate(rule, ticker, raw, events, start, end, dates)
        prices = {
            b.trade_date.isoformat(): b
            for b in adjusted_bars([b for b in raw if usable(b)], events)
        }
        trades = []
        for variant in VARIANTS:
            trades.extend(
                trades_for(
                    ticker,
                    payload["signals"],
                    prices,
                    turnover,
                    kind,
                    variant,
                    costs,
                    benchmark,
                    dates,
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
            reason=f"{type(exc).__name__}: {exc}",
            elapsed_seconds=time.perf_counter() - started,
        )


def run_research(args, factory=SessionLocal):
    started = time.perf_counter()
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
                benchmark = load_benchmark(db, warm, args.end, dates)
            except Exception as exc:
                benchmark_reason = f"{type(exc).__name__}: {exc}"
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
            variants=[asdict(v) for v in VARIANTS],
        ),
        universe_size=len(tickers),
        succeeded=sum(r["reason"] is None for r in results),
        skipped=[dict(ticker=r["ticker"], reason=r["reason"]) for r in results if r["reason"]],
        benchmark_reason=benchmark_reason,
        trades=trades,
        stocks=[{k: v for k, v in r.items() if k not in ("trades", "opens")} for r in results],
        statistics=summarize(trades, start, args.end),
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
    if args.out_json.resolve() == args.out_md.resolve():
        parser.error("JSON 與 Markdown 路徑不可相同")
    result = run_research(args)
    args.out_json.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8"
    )
    args.out_md.write_text(markdown(result), encoding="utf-8")


if __name__ == "__main__":
    main()
