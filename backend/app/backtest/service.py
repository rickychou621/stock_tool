import copy
import hashlib
import json
import logging
import statistics
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import defer, selectinload

from app.backtest.coordination import acquire
from app.backtest.costs_benchmark import benchmark_return, enrich, load_benchmark
from app.backtest.data import load_trading_dates, prepare_data
from app.backtest.models import BacktestResult, BacktestTask
from app.backtest.simulation import metrics, simulate
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.market_data.models import Stock
from app.market_data.price_event_sync import sync_market_price_events
from app.market_scan.models import MarketInstrument
from app.rules.models import WatchRule
from app.rules.preparation import history_days
from app.trading_costs import TradingCosts
from app.watchlist.models import HoldingsWatchlist

logger = logging.getLogger(__name__)


def utcnow():
    return datetime.now(UTC).replace(tzinfo=None)


def years_ago(day, years=3):
    try:
        return day.replace(year=day.year - years)
    except ValueError:
        return day.replace(year=day.year - years, day=28)


def rule_snapshot(rule):
    return dict(
        id=rule.id,
        name=rule.name,
        logic_operator=rule.logic_operator,
        evaluation_frequency=getattr(rule, "evaluation_frequency", None) or "daily",
        conditions=[
            dict(
                condition_id=c.condition_id,
                params=copy.deepcopy(c.params),
                sort_order=c.sort_order,
                role=getattr(c, "role", None) or "premise",
            )
            for c in rule.conditions
        ],
    )


def definition_fingerprint(snapshot) -> str:
    definition = {
        "logic_operator": snapshot["logic_operator"],
        "evaluation_frequency": snapshot.get("evaluation_frequency") or "daily",
        "conditions": [
            {
                "condition_id": c["condition_id"],
                "params": c["params"],
                "sort_order": c["sort_order"],
                "role": c.get("role") or "premise",
            }
            for c in sorted(snapshot["conditions"], key=lambda c: c["sort_order"])
        ],
    }
    return hashlib.sha256(
        json.dumps(definition, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def restore_rule(snapshot):
    return SimpleNamespace(
        **{
            "evaluation_frequency": "daily",
            **snapshot,
            "conditions": [
                SimpleNamespace(**{"role": "premise", **c}) for c in snapshot["conditions"]
            ],
        }
    )


def process_stock(session_factory, ticker, snapshots, start, end, warm_start, dates):
    with session_factory() as db:
        raw, events = prepare_data(db, ticker, warm_start, end, dates)
        results = []
        for definition in snapshots:
            rule = restore_rule(definition)
            payload = simulate(rule, ticker, raw, events, start, end, dates)
            payload["definition"] = definition
            results.append((rule.id, rule.name, payload))
        return results


class BacktestBusy(ValueError):
    pass


class BacktestManager:
    def __init__(
        self,
        session_factory=SessionLocal,
        calendar=load_trading_dates,
        worker=process_stock,
        benchmark_loader=load_benchmark,
    ):
        self.benchmark_loader = benchmark_loader
        self.sessions = session_factory
        self.calendar = calendar
        self.worker = worker
        self.executor = None

    def recover(self):
        lease = acquire(self.sessions)
        if lease is None:
            return
        try:
            with self.sessions() as db:
                task = db.get(BacktestTask, 1)
                if task and task.status == "running":
                    task.status = "interrupted"
                    task.finished_at = utcnow()
                    task.errors = [
                        *task.errors,
                        {"ticker": None, "reason": "後端重啟，未完成回測已中斷；不自動續跑。"},
                    ]
                    db.commit()
        finally:
            lease.close()

    def close(self):
        if self.executor:
            self.executor.shutdown(wait=True)
            self.executor = None

    def start(self, rule_ids, now=None):
        lease = acquire(self.sessions)
        if lease is None:
            raise BacktestBusy("已有回測執行中，請等待完成；不建立佇列。")
        submitted = False
        try:
            now = (now or datetime.now(ZoneInfo("Asia/Taipei"))).astimezone(ZoneInfo("Asia/Taipei"))
            end = now.date() if now.hour >= 18 else now.date() - timedelta(days=1)
            start = years_ago(end)
            with self.sessions() as db:
                task = db.get(BacktestTask, 1)
                if task and task.status == "running":
                    raise BacktestBusy("上一任務尚未結束，請確認後端狀態。")
                rules = list(
                    db.scalars(
                        select(WatchRule)
                        .options(selectinload(WatchRule.conditions))
                        .where(WatchRule.id.in_(rule_ids), WatchRule.is_enabled.is_(True))
                    )
                )
                if not rule_ids or len(rules) != len(set(rule_ids)):
                    raise ValueError("請選擇至少一個目前已啟用的戰法。")
                snapshots = [rule_snapshot(rule) for rule in rules]
                for rule in rules:
                    if not rule.conditions:
                        raise ValueError(f"{rule.name} 沒有條件，無法回測")
                try:
                    warm_days = max(history_days(rule) for rule in rules)
                except (KeyError, ValueError, TypeError) as exc:
                    raise ValueError(f"所選戰法不支援歷史計算：{exc}") from exc
                items = list(
                    db.execute(
                        select(Stock.ticker, Stock.name)
                        .join(HoldingsWatchlist, HoldingsWatchlist.ticker == Stock.ticker)
                        .where(HoldingsWatchlist.is_active.is_(True))
                        .distinct()
                    )
                )
                if not items:
                    raise ValueError("觀察清單沒有可回測股票")
                batch = str(uuid4())
                db.merge(
                    BacktestTask(
                        id=1,
                        batch_id=batch,
                        status="running",
                        started_at=utcnow(),
                        finished_at=None,
                        start_date=start,
                        end_date=end,
                        rule_ids=sorted(set(rule_ids)),
                        tickers=[i.ticker for i in items],
                        total=len(items),
                        succeeded=0,
                        failed=0,
                        errors=[],
                        context_json={
                            "costSnapshot": TradingCosts.from_settings(get_settings()).snapshot()
                        },
                    )
                )
                for row in db.scalars(
                    select(BacktestResult).where(
                        BacktestResult.ticker.in_([i.ticker for i in items]),
                        BacktestResult.rule_id.in_(rule_ids),
                    )
                ):
                    row.stale = True
                db.commit()
            if self.executor is None:
                self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="backtest-job")
            try:
                self.executor.submit(
                    self._run,
                    lease,
                    batch,
                    items,
                    snapshots,
                    start,
                    end,
                    start - timedelta(days=warm_days),
                )
            except Exception as exc:
                self._fail(batch, f"背景任務無法啟動：{exc}")
                raise
            submitted = True
            return batch
        finally:
            if not submitted:
                lease.close()

    def _fail(self, batch, reason):
        with self.sessions() as db:
            task = db.get(BacktestTask, 1)
            if task and task.batch_id == batch:
                task.status = "failed"
                task.failed = task.total - task.succeeded
                task.finished_at = utcnow()
                task.errors = [*task.errors, {"ticker": None, "reason": reason}]
                db.commit()

    def _run(self, lease, batch, items, snapshots, start, end, warm_start):
        try:
            dates = self.calendar(self.sessions, warm_start, end)
            in_window = [d for d in dates if d >= start]
            if not in_window:
                raise ValueError("回測期間沒有可確認的交易日")
            end = in_window[-1]
            with self.sessions() as db:
                task = db.get(BacktestTask, 1)
                task.end_date = end
                costs = task.context_json["costSnapshot"]
                kinds = dict(
                    db.execute(select(MarketInstrument.ticker, MarketInstrument.kind)).all()
                )
                db.commit()
            event_sync = sync_market_price_events(self.sessions, warm_start, end)
            if event_sync.warnings:
                with self.sessions() as db:
                    task = db.get(BacktestTask, 1)
                    task.errors = [
                        *task.errors,
                        *[{"ticker": None, "reason": warning} for warning in event_sync.warnings],
                    ]
                    db.commit()
            benchmark = self.benchmark_loader(self.sessions, warm_start, end, dates)
            with self.sessions() as db:
                task = db.get(BacktestTask, 1)
                task.context_json = {"costSnapshot": costs, "benchmark": benchmark}
                db.commit()
            with ThreadPoolExecutor(max_workers=3, thread_name_prefix="backtest-stock") as pool:
                futures = {
                    pool.submit(
                        self.worker,
                        self.sessions,
                        item.ticker,
                        snapshots,
                        start,
                        end,
                        warm_start,
                        dates,
                    ): item
                    for item in items
                }
                for future in as_completed(futures):
                    item = futures[future]
                    try:
                        results = future.result()
                        if {r[0] for r in results} != {r["id"] for r in snapshots}:
                            raise ValueError("回測結果不完整，未取代舊結果")
                        with self.sessions() as db:
                            for rule_id, name, payload in results:
                                enrich(payload, costs, kinds.get(item.ticker), benchmark)
                                row = db.scalar(
                                    select(BacktestResult).where(
                                        BacktestResult.ticker == item.ticker,
                                        BacktestResult.rule_id == rule_id,
                                    )
                                )
                                if row is None:
                                    row = BacktestResult(ticker=item.ticker, rule_id=rule_id)
                                    db.add(row)
                                row.stock_name, row.rule_name = item.name, name
                                row.batch_id, row.stale = batch, False
                                row.calculated_at, row.payload = utcnow(), payload
                                row.summary = {
                                    k: v
                                    for k, v in payload.items()
                                    if k not in ("signals", "definition")
                                }
                                row.summary["definitionFingerprint"] = definition_fingerprint(
                                    payload["definition"]
                                )
                                row.summary["trades"] = [
                                    {
                                        k: t.get(k)
                                        for k in (
                                            "status",
                                            "entryDate",
                                            "exitDate",
                                            "returnRate",
                                            "grossReturnRate",
                                            "excessReturn",
                                            "ticker",
                                            "pendingSide",
                                        )
                                    }
                                    for t in payload["trades"]
                                ]
                            db.get(BacktestTask, 1).succeeded += 1
                            db.commit()  # All selected pairs AND progress in one transaction.
                    except Exception as exc:
                        with self.sessions() as db:
                            task = db.get(BacktestTask, 1)
                            task.failed += 1
                            task.errors = [
                                *task.errors,
                                {"ticker": item.ticker, "reason": str(exc)[:1500]},
                            ]
                            db.commit()
            with self.sessions() as db:
                task = db.get(BacktestTask, 1)
                task.status = (
                    "partial_failure"
                    if task.failed and task.succeeded
                    else ("failed" if task.failed else "succeeded")
                )
                task.finished_at = utcnow()
                db.commit()
        except Exception as exc:
            logger.exception("Backtest %s failed", batch)
            self._fail(batch, str(exc))
        finally:
            lease.close()


def average_excess(trades):
    values = [t["excessReturn"] for t in trades if t.get("excessReturn") is not None]
    return sum(values) / len(values) if values else None


def median_or_none(values):
    return statistics.median(values) if values else None


def drawdown_summary(values):
    values = [item for item in values if item[3] >= 3]
    sample_count = len(values)
    eligible = values if sample_count >= 5 else []
    largest = max(eligible, key=lambda item: item[0]) if eligible else (None, None, None)
    median = median_or_none([item[0] for item in eligible])
    return dict(
        maxDrawdownSampleCount=sample_count,
        maxDrawdown=median,
        maxDrawdownMedian=median,
        maxDrawdownMax=largest[0],
        maxDrawdownMaxTicker=largest[1],
        maxDrawdownMaxName=largest[2],
    )


def read_report(db):
    task = db.get(BacktestTask, 1)
    if task is None:
        return dict(task=None, overall=[], stocks=[], staleInfo=None, scopeDiff=None)
    active_tickers = set(db.scalars(
        select(HoldingsWatchlist.ticker).where(HoldingsWatchlist.is_active.is_(True))
    ))
    task_tickers = set(task.tickers)
    scope_diff = (
        dict(
            added=sorted(active_tickers - task_tickers),
            removed=sorted(task_tickers - active_tickers),
        )
        if active_tickers != task_tickers else None
    )
    rows = list(
        db.scalars(
            select(BacktestResult)
            .options(defer(BacktestResult.payload))
            .where(
                BacktestResult.ticker.in_(task.tickers), BacktestResult.rule_id.in_(task.rule_ids)
            )
        )
    )
    current_rules = {
        rule.id: rule
        for rule in db.scalars(
            select(WatchRule)
            .options(selectinload(WatchRule.conditions))
            .where(WatchRule.id.in_({row.rule_id for row in rows}))
        )
    }
    current_fingerprints = {
        rule_id: definition_fingerprint(rule_snapshot(rule))
        for rule_id, rule in current_rules.items()
    }
    rerun_rule_ids, changed_rule_ids = set(), set()
    stocks, grouped = [], {}
    for row in rows:
        stale = row.stale or row.batch_id != task.batch_id
        p = row.summary
        legacy = p.get("schemaVersion") != 2
        definition_changed = (
            not p.get("definitionFingerprint")
            or p["definitionFingerprint"] != current_fingerprints.get(row.rule_id)
        )
        if stale or legacy or definition_changed:
            rerun_rule_ids.add(row.rule_id)
        if definition_changed:
            changed_rule_ids.add(row.rule_id)
        stocks.append(
            dict(
                id=row.id,
                batchId=row.batch_id,
                ticker=row.ticker,
                stockName=row.stock_name,
                ruleId=row.rule_id,
                ruleName=row.rule_name,
                stale=stale,
                calculatedAt=row.calculated_at.replace(tzinfo=UTC).isoformat(),
                actualStart=p["actualStart"],
                actualEnd=p["actualEnd"],
                metrics=metrics([]) if legacy else p["metrics"],
                needsRerun=legacy or definition_changed,
                **(
                    {"rerunReason": "戰法定義已變更，需重新回測"}
                    if definition_changed
                    else {}
                ),
                grossMetrics=p.get("grossMetrics", p["metrics"]),
                costSnapshot=p.get("costSnapshot"),
                averageExcessReturn=p.get("averageExcessReturn"),
                benchmarkBuyHoldReturn=p.get("benchmarkBuyHoldReturn"),
                benchmarkReason=p.get("benchmarkReason"),
                warnings=p.get("warnings", []),
                openCount=sum(t["status"] == "open" for t in p["trades"]),
                unfilledCount=sum(
                    t["status"] == "unfilled" or bool(t.get("pendingSide")) for t in p["trades"]
                ),
                skippedSessions=p.get("skippedSessions", 0),
            )
        )
        if not legacy:
            group = grouped.setdefault(
                row.rule_id,
                dict(
                    ruleId=row.rule_id,
                    ruleName=row.rule_name,
                    stockCount=0,
                    stale=False,
                    actualStart=p["actualStart"],
                    actualEnd=p["actualEnd"],
                    trades=[],
                    excessReturns=[],
                    evaluationFrequency=(
                        getattr(current_rules.get(row.rule_id), "evaluation_frequency", None)
                        or "daily"
                    ),
                    compounds=[],
                    grossCompounds=[],
                    drawdowns=[],
                    grossDrawdowns=[],
                ),
            )
            group["stale"] |= stale or definition_changed
            group["stockCount"] += 1
            group["actualStart"] = min(group["actualStart"], p["actualStart"])
            group["actualEnd"] = max(group["actualEnd"], p["actualEnd"])
            group["trades"].extend(p["trades"])
            if p["metrics"].get("compoundReturn") is not None:
                group["compounds"].append(p["metrics"]["compoundReturn"])
            compound = p["metrics"].get("compoundReturn")
            benchmark = p.get("benchmarkBuyHoldReturn")
            if compound is not None and benchmark is not None:
                group["excessReturns"].append(compound - benchmark)
            gross_compound = p.get("grossMetrics", p["metrics"]).get("compoundReturn")
            if gross_compound is not None:
                group["grossCompounds"].append(gross_compound)
            for metric_key, group_key in (
                ("metrics", "drawdowns"), ("grossMetrics", "grossDrawdowns")
            ):
                drawdown = p.get(metric_key, p["metrics"]).get("maxDrawdown")
                if drawdown is not None:
                    group[group_key].append(
                        (drawdown, row.ticker, row.stock_name, p["metrics"]["tradeCount"])
                    )
    overall = []
    for group in grouped.values():
        overall.append(
            {
                **{
                    k: v for k, v in group.items()
                    if k not in (
                        "trades", "compounds", "grossCompounds", "drawdowns", "grossDrawdowns",
                        "excessReturns"
                    )
                },
                # Chaining every stock's trades into one compound is meaningless across
                # stocks; report the median of per-stock compound returns instead.
                "metrics": {
                    **metrics(group["trades"]),
                    "excessReturnMedian": median_or_none(group["excessReturns"]),
                    "compoundReturn": median_or_none(group["compounds"]),
                    **drawdown_summary(group["drawdowns"]),
                },
                "grossMetrics": {
                    **metrics(
                        [{**t, "returnRate": t["grossReturnRate"]} for t in group["trades"]]
                    ),
                    "compoundReturn": median_or_none(group["grossCompounds"]),
                    **drawdown_summary(group["grossDrawdowns"]),
                },
                "averageExcessReturn": average_excess(group["trades"]),
                "benchmarkBuyHoldReturn": benchmark_return(
                    (task.context_json or {}).get("benchmark", {}),
                    group["actualStart"],
                    group["actualEnd"],
                    "close",
                ),
            }
        )
    changed_at = max(
        (current_rules[rule_id].updated_at for rule_id in changed_rule_ids
         if rule_id in current_rules and current_rules[rule_id].updated_at is not None),
        default=None,
    )
    stale_info = (
        dict(
            reason="definition" if changed_rule_ids else "data",
            changedAt=changed_at.replace(tzinfo=UTC).isoformat() if changed_at else None,
            ruleIds=sorted(rerun_rule_ids),
        )
        if rerun_rule_ids else None
    )
    return dict(
        staleInfo=stale_info,
        scopeDiff=scope_diff,
        task=dict(
            batchId=task.batch_id,
            status=task.status,
            startedAt=task.started_at.replace(tzinfo=UTC).isoformat(),
            finishedAt=task.finished_at.replace(tzinfo=UTC).isoformat()
            if task.finished_at
            else None,
            startDate=task.start_date.isoformat(),
            endDate=task.end_date.isoformat(),
            ruleIds=task.rule_ids,
            tickers=task.tickers,
            total=task.total,
            completed=task.succeeded + task.failed,
            succeeded=task.succeeded,
            failed=task.failed,
            errors=task.errors,
            costSnapshot=(task.context_json or {}).get("costSnapshot"),
        ),
        overall=overall,
        stocks=stocks,
    )


manager = BacktestManager()


def build_equity_curve(trades: list[dict], start: str, end: str, benchmark: dict) -> dict:
    values = {start: 1.0}
    value = 1.0
    closed = sorted(
        (t for t in trades if t["status"] == "closed"
         and t.get("netReturnRate") is not None and t.get("exitDate")),
        key=lambda t: t["exitDate"],
    )
    for trade in closed:
        value *= 1 + trade["netReturnRate"]
        values[trade["exitDate"]] = value
    if max(values) < end:
        values[end] = value
    opening = benchmark.get(start, {}).get("open")
    return {
        "strategy": [{"date": day, "value": amount} for day, amount in sorted(values.items())],
        "benchmark": [
            {"date": day, "value": bar["close"] / opening}
            for day, bar in sorted(benchmark.items()) if start <= day <= end
        ] if opening else [],
    }
