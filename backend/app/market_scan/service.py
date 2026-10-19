"""Single stage-three owner. Workers calculate outside the publication transaction."""

import copy
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select
from sqlalchemy.orm import selectinload

from app.backtest.data import load_trading_dates
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.data_source.notifier import TelegramNotifier
from app.market_scan.batch_data import synchronize
from app.market_scan.coordination import acquire
from app.market_scan.data import required_days
from app.market_scan.models import ScanError, ScanSettings, ScanTask
from app.market_scan.publication import publish
from app.market_scan.rate_limit import RateLimiter
from app.market_scan.signal_tracking import backfill
from app.market_scan.universe import refresh_universe
from app.market_scan.worker import Outcome, process_stock
from app.rules.models import WatchRule
from app.scheduler.calendar import TwseCalendar

TZ = ZoneInfo("Asia/Taipei")
logger = logging.getLogger(__name__)


def load_market_trading_dates(factory, start, end):
    return load_trading_dates(factory, start, end, allow_empty_current_month=True)


class ScanBusy(Exception):
    pass


def settings_row(db):
    row = db.get(ScanSettings, 1)
    # Migration seeds the singleton. SQLite tests may start without seed data.
    if row is None:
        row = ScanSettings(id=1, enabled=True, rule_ids=None)
        db.add(row)
        db.commit()
    return row


def chosen_rules(db, ids=None):
    query = (
        select(WatchRule)
        .where(WatchRule.is_enabled.is_(True))
        .options(selectinload(WatchRule.conditions))
        .order_by(WatchRule.id)
    )
    rules = list(db.scalars(query))
    if ids is not None:
        if set(ids) - {r.id for r in rules}:
            raise ValueError("戰法不存在或未啟用，請重新選擇")
        rules = [r for r in rules if r.id in ids]
    return [
        SimpleNamespace(
            id=r.id,
            name=r.name,
            logic_operator=r.logic_operator,
            conditions=[
                SimpleNamespace(
                    condition_id=c.condition_id,
                    params=copy.deepcopy(c.params),
                    sort_order=c.sort_order,
                )
                for c in r.conditions
            ],
        )
        for r in rules
    ]


def terminal(outcomes):
    if not any(o.succeeded for o in outcomes):
        return "failed"
    return "partial_completed" if any(o.failed or o.insufficient for o in outcomes) else "completed"


class MarketScanManager:
    def __init__(
        self,
        factory,
        *,
        calendar=load_market_trading_dates,
        universe=refresh_universe,
        worker=process_stock,
        notifier=None,
        settings=None,
        batch_prepare=synchronize,
    ):
        self.factory, self.calendar, self.universe, self.worker = (
            factory,
            calendar,
            universe,
            worker,
        )
        self.batch_prepare = batch_prepare
        self.settings = settings or get_settings()
        self.notifier = notifier or TelegramNotifier(self.settings)
        self.limiter = RateLimiter(self.settings.finmind_scan_requests_per_minute)
        self.executor = None

    def start(self, rule_ids=None, *, kind="scan", source="manual", now=None, mode="prices"):
        if mode not in ("prices", "dividends"):
            raise ValueError("初始化模式無效")
        lease = acquire(self.factory)
        if lease is None:
            raise ScanBusy("初始化或全市場掃描正在執行，請等候完成")
        batch_id = str(uuid4())
        now = now or datetime.now(TZ)
        try:
            with self.factory() as db:
                settings = settings_row(db)
                if source == "automatic":
                    if (now.astimezone(TZ).hour, now.astimezone(TZ).minute) != (19, 0):
                        return None
                    if (
                        not settings.enabled
                        or settings.last_attempt_date == now.astimezone(TZ).date()
                    ):
                        return None
                    settings.last_attempt_date = now.astimezone(TZ).date()
                    rule_ids = settings.rule_ids
                elif rule_ids is None:
                    rule_ids = settings.rule_ids
                if source == "automatic":
                    active = chosen_rules(db)
                    rules = [r for r in active if rule_ids is None or r.id in rule_ids]
                else:
                    rules = chosen_rules(db, rule_ids)
                if not rules and source != "automatic":
                    raise ValueError("請至少選擇一個已啟用戰法")
                db.execute(delete(ScanError).where(ScanError.kind == kind))
                task = ScanTask(
                    kind=kind,
                    batch_id=batch_id,
                    source=source,
                    status="running",
                    started_at=datetime.utcnow(),
                    rules=[dict(id=r.id, name=r.name) for r in rules],
                    warnings=[],
                    baseline=None,
                    finished_at=None,
                    total=0,
                    processed=0,
                    succeeded=0,
                    failed=0,
                    insufficient=0,
                )
                if not rules:
                    task.status, task.finished_at, task.warnings = (
                        "skipped",
                        datetime.utcnow(),
                        ["未選擇戰法"],
                    )
                db.merge(task)
                db.commit()
            if not rules:
                return batch_id
            # No queued jobs: lease was claimed before executor creation / HTTP acceptance.
            if self.executor:
                self.executor.shutdown(wait=False)
            self.executor = ThreadPoolExecutor(
                max_workers=1, thread_name_prefix="market-coordinator"
            )
            self.executor.submit(self._run, batch_id, kind, source, rules, now, lease, mode)
            lease = None
            return batch_id
        finally:
            if lease is not None:
                lease.close()

    def _run(self, batch_id, kind, source, rules, now, lease, mode):
        try:
            cutoff = now.astimezone(TZ).date()
            if now.astimezone(TZ).hour < 18:
                cutoff -= timedelta(days=1)
            dates = self.calendar(
                self.factory, cutoff - timedelta(days=required_days(rules) + 35), cutoff
            )
            if not dates:
                raise ValueError("無法確認掃描基準交易日")
            with self.factory() as db:
                # Refresh for initialization, automatic scans and manual scans as well.
                instruments, warning = self.universe(db, cutoff)
                task = db.get(ScanTask, kind)
                task.total, task.baseline = len(instruments), dates[-1]
                if warning:
                    task.warnings = [*task.warnings, warning]
                db.commit()

            def progress(message):
                lease.verify()
                with self.factory() as db:
                    task = db.get(ScanTask, kind)
                    task.warnings = [w for w in task.warnings if not w.startswith("批次行情 ")]
                    task.warnings = [*task.warnings, message]
                    db.commit()

            warnings, errors = self.batch_prepare(
                self.factory,
                instruments,
                rules,
                kind,
                dates,
                self.limiter,
                lease.verify,
                progress=progress,
                mode=mode,
            )
            lease.verify()
            with self.factory() as db:
                task = db.get(ScanTask, kind)
                task.warnings = [w for w in task.warnings if not w.startswith("批次行情 ")]
                task.warnings = [*task.warnings, *warnings]
                db.add_all(
                    [
                        ScanError(
                            kind=kind,
                            batch_id=batch_id,
                            ticker=ticker,
                            status="warning",
                            reason=reason[:1000],
                        )
                        for ticker, reason in errors
                    ]
                )
                db.commit()
            outcomes = []
            with ThreadPoolExecutor(
                max_workers=self.settings.market_scan_workers, thread_name_prefix="market-stock"
            ) as pool:
                futures = {
                    pool.submit(
                        self.worker, self.factory, item, rules, kind, dates, self.limiter
                    ): item[0]
                    for item in instruments
                }
                for future in as_completed(futures):
                    ticker = futures[future]
                    try:
                        outcome = future.result()
                    except Exception as exc:
                        reason = f"{type(exc).__name__}: {str(exc)[:800]}"
                        outcome = Outcome(
                            ticker,
                            rules={r.id: ("stale", reason) for r in rules},
                            errors=[(None, "stale", reason)],
                        )
                    lease.verify()
                    outcomes.append(outcome)
                    with self.factory() as db:
                        task = db.get(ScanTask, kind)
                        task.processed += 1
                        task.succeeded += int(outcome.succeeded)
                        task.failed += int(outcome.failed)
                        task.insufficient += int(outcome.insufficient)
                        db.add_all(
                            [
                                ScanError(
                                    kind=kind,
                                    batch_id=batch_id,
                                    ticker=ticker,
                                    rule_id=rid,
                                    status=status,
                                    reason=reason[:1000],
                                )
                                for rid, status, reason in outcome.errors
                            ]
                        )
                        db.commit()
            lease.verify()
            status, finished = terminal(outcomes), datetime.utcnow()
            if (
                kind == "initialize"
                and status == "completed"
                and (errors or any("失敗" in warning for warning in warnings))
            ):
                status = "partial_completed"
            with self.factory() as db:
                task = db.get(ScanTask, kind)
                if kind == "scan":
                    metadata = dict(
                        batchId=batch_id,
                        source=source,
                        status=status,
                        finishedAt=finished.isoformat() + "Z",
                        baseline=dates[-1].isoformat(),
                        rules=task.rules,
                        total=task.total,
                        succeeded=task.succeeded,
                        failed=task.failed,
                        insufficient=task.insufficient,
                        warnings=task.warnings,
                    )
                    publish(db, batch_id, outcomes, metadata)
                    try:
                        backfill(self.factory, dates[-1], lease.verify)
                    except Exception as exc:
                        # Publication has committed: tracking failure cannot undo it.
                        db.rollback()
                        task = db.get(ScanTask, kind)
                        task.warnings = [
                            *task.warnings,
                            f"績效回填失敗（{type(exc).__name__}），下次掃描再補",
                        ]
                        db.commit()
                else:
                    task.status, task.finished_at = status, finished
                    db.commit()
        except Exception as exc:
            logger.exception("Market %s failed", kind)
            with self.factory() as db:
                task = db.get(ScanTask, kind)
                if task.batch_id != batch_id:
                    return
                task.status, task.finished_at = "failed", datetime.utcnow()
                task.warnings = [
                    *task.warnings,
                    f"任務失敗：{type(exc).__name__}: {str(exc)[:300]}",
                ]
                db.add(
                    ScanError(kind=kind, batch_id=batch_id, status="failed", reason=str(exc)[:1000])
                )
                db.commit()
        finally:
            try:
                if kind == "scan":
                    self.notify(batch_id)
            finally:
                lease.close()

    def notify(self, batch_id):
        with self.factory() as db:
            task = db.get(ScanTask, "scan")
            if task.batch_id != batch_id:
                return
            label = {
                "completed": "全市場掃描完成",
                "partial_completed": "掃描完成，部分資料處理失敗",
                "failed": "全市場掃描失敗",
            }.get(task.status)
            if not label:
                return
            finished = (
                task.finished_at.replace(tzinfo=ZoneInfo("UTC"))
                .astimezone(TZ)
                .strftime("%Y-%m-%d %H:%M:%S")
            )
        try:
            self.notifier.send_alert(f"{label}\n完成時間：{finished}（台北）")
        except Exception as exc:
            # Do not log httpx URLs: Telegram token is part of the request URL.
            with self.factory() as db:
                task = db.get(ScanTask, "scan")
                if task.batch_id == batch_id:
                    task.warnings = [
                        *task.warnings,
                        f"Telegram 完成通知失敗或未設定（{type(exc).__name__}）",
                    ]
                    db.commit()

    def record_schedule_failure(self, day, reason):
        lease = acquire(self.factory)
        if lease is None:
            return
        try:
            with self.factory() as db:
                settings = settings_row(db)
                if settings.last_attempt_date == day or not settings.enabled:
                    return
                settings.last_attempt_date = day
                batch_id = str(uuid4())
                db.execute(delete(ScanError).where(ScanError.kind == "scan"))
                db.merge(
                    ScanTask(
                        kind="scan",
                        batch_id=batch_id,
                        source="automatic",
                        status="failed",
                        started_at=datetime.utcnow(),
                        finished_at=datetime.utcnow(),
                        baseline=None,
                        rules=[],
                        total=0,
                        processed=0,
                        succeeded=0,
                        failed=0,
                        insufficient=0,
                        warnings=[reason],
                    )
                )
                db.add(ScanError(kind="scan", batch_id=batch_id, status="failed", reason=reason))
                db.commit()
            self.notify(batch_id)
        finally:
            lease.close()

    def recover(self):
        lease = acquire(self.factory)
        if lease is None:
            return
        try:
            with self.factory() as db:
                for task in db.scalars(
                    select(ScanTask).where(ScanTask.status.in_(["pending", "running"]))
                ):
                    task.status, task.finished_at = "interrupted", datetime.utcnow()
                    task.warnings = [*task.warnings, "後端重啟，任務已中斷；不自動續跑"]
                db.commit()
        finally:
            lease.close()

    def close(self):
        if self.executor:
            self.executor.shutdown(wait=True)


manager = MarketScanManager(SessionLocal)


def run_daily_market_scan(now=None, calendar=None, job_manager=None):
    now, calendar, job_manager = (
        now or datetime.now(TZ),
        calendar or TwseCalendar(),
        job_manager or manager,
    )
    local = now.astimezone(TZ)
    if (local.hour, local.minute) != (19, 0):
        return
    with job_manager.factory() as db:
        settings = settings_row(db)
        if not settings.enabled or settings.last_attempt_date == local.date():
            return
    try:
        if not calendar.is_trading_day(local.date()):
            return
        job_manager.start(source="automatic", now=now)
    except ScanBusy:
        # No queue, no catch-up. Record the attempt without replacing the live task.
        with job_manager.factory() as db:
            settings_row(db).last_attempt_date = local.date()
            for task in db.scalars(select(ScanTask).where(ScanTask.status == "running")):
                task.warnings = [*task.warnings, "19:00 自動掃描因階段三任務執行中而略過"]
            db.commit()
    except Exception as exc:
        job_manager.record_schedule_failure(
            local.date(), f"交易日判定或排程啟動失敗：{type(exc).__name__}，未重試"
        )
        logger.exception("Automatic market scan could not start; no retry")
