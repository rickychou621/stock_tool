"""Daily watchlist update and Telegram summary, without retries or catch-up."""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.data_source.notifier import TelegramNotifier
from app.market_data.models import Stock
from app.market_data.price_event_sync import sync_market_price_events
from app.rules.models import WatchRule
from app.scheduler.calendar import TwseCalendar
from app.scheduler.coordination import coordinator_lock
from app.scheduler.models import ScheduleError, ScheduleRun
from app.scheduler.service import enabled_rule_ids, settings_row, utcnow
from app.scheduler.worker import process_stock
from app.watchlist.models import HoldingsWatchlist, WatchlistEvaluation
from app.watchlist.notification import messages

logger = logging.getLogger(__name__)
TAIPEI = ZoneInfo("Asia/Taipei")


def _run_daily_watchlist(
    *, now=None, session_factory=SessionLocal, calendar=None, worker=process_stock, notifier=None
):
    now = (now or datetime.now(TAIPEI)).astimezone(TAIPEI)
    if (now.hour, now.minute) != (18, 0):
        return  # Never run a missed job later, including after process restart.
    day = now.date()
    with session_factory() as db:
        config = settings_row(db)
        if not config.enabled or config.last_attempt_date == day:
            return
    calendar_error = None
    try:
        if not (calendar or TwseCalendar()).is_trading_day(day):
            return
    except Exception as exc:
        calendar_error = f"交易日查詢失敗，未更新股票：{exc}"
    batch = str(uuid4())
    with session_factory() as db:
        config = settings_row(db, lock=True)
        if not config.enabled or config.last_attempt_date == day:
            return
        config.last_attempt_date = day
        selected = config.rule_ids
        active = enabled_rule_ids(db)
        rule_ids = active if selected is None else sorted(set(selected) & set(active))
        items = list(
            db.execute(
                select(HoldingsWatchlist.id, HoldingsWatchlist.ticker).where(
                    HoldingsWatchlist.is_active.is_(True)
                )
            )
        )
        previous = db.get(ScheduleRun, 1)
        if previous and previous.status == "running":
            db.add(
                ScheduleError(
                    batch_id=previous.batch_id,
                    ticker=None,
                    occurred_at=utcnow(),
                    reason="上次執行中斷，未自動補跑",
                )
            )
        db.merge(
            ScheduleRun(
                id=1,
                batch_id=batch,
                trade_date=day,
                started_at=utcnow(),
                finished_at=None,
                status="running",
                total=len(items),
                succeeded=0,
                failed=0,
            )
        )
        db.commit()  # Persist the claim before any external calls / worker threads.
    try:
        if calendar_error:
            raise ValueError(calendar_error)
        event_sync = sync_market_price_events(session_factory, day - timedelta(days=730), day)
        if event_sync.warnings:
            with session_factory() as db:
                for warning in event_sync.warnings:
                    logger.warning("Watchlist price events: %s", warning)
                    db.add(
                        ScheduleError(
                            batch_id=batch, ticker=None, occurred_at=utcnow(), reason=warning
                        )
                    )
                db.commit()
        with ThreadPoolExecutor(max_workers=3, thread_name_prefix="watchlist") as pool:
            futures = {
                pool.submit(
                    worker, session_factory, item.id, item.ticker, rule_ids, day
                ): item.ticker
                for item in items
            }
            for future in as_completed(futures):
                ticker = futures[future]
                try:
                    failures = future.result()
                except Exception as exc:
                    failures = [f"股票處理失敗：{exc}"]
                with session_factory() as db:
                    run = db.get(ScheduleRun, 1)
                    if failures:
                        run.failed += 1
                        for reason in failures:
                            db.add(
                                ScheduleError(
                                    batch_id=batch,
                                    ticker=ticker,
                                    occurred_at=utcnow(),
                                    reason=reason,
                                )
                            )
                    else:
                        run.succeeded += 1
                    db.commit()
        with session_factory() as db:
            run = db.get(ScheduleRun, 1)
            run.status = (
                "partial_failure"
                if run.failed and run.succeeded
                else ("failed" if run.failed else "succeeded")
            )
            run.finished_at = utcnow()
            failed = run.failed
            db.commit()
    except Exception as exc:
        logger.exception("Watchlist batch %s failed", batch)
        with session_factory() as db:
            run = db.get(ScheduleRun, 1)
            run.status = "failed"
            run.failed = run.total - run.succeeded
            run.finished_at = utcnow()
            db.add(
                ScheduleError(batch_id=batch, ticker=None, occurred_at=utcnow(), reason=str(exc))
            )
            db.commit()

        _send_notifications(
            session_factory, batch, notifier,
            [f"觀察清單排程失敗｜{day:%m/%d}｜{str(exc)[:120]}"],
        )
        return

    # Query scalar columns in one join; never lazily load a rule or stock per holding.
    with session_factory() as db:
        evaluations = list(db.execute(
            select(HoldingsWatchlist.ticker, Stock.name, WatchRule.name, WatchlistEvaluation.result)
            .select_from(WatchlistEvaluation)
            .join(HoldingsWatchlist, HoldingsWatchlist.id == WatchlistEvaluation.item_id)
            .join(Stock, Stock.ticker == HoldingsWatchlist.ticker)
            .join(WatchRule, WatchRule.id == WatchlistEvaluation.rule_id)
            .where(
                HoldingsWatchlist.is_active.is_(True),
                HoldingsWatchlist.id.in_([item.id for item in items]),
                WatchlistEvaluation.rule_id.in_(rule_ids),
                # A failed stock keeps yesterday's result marked stale (data_version -1);
                # never send an old stop price as today's. It is counted in failed instead.
                WatchlistEvaluation.data_version == Stock.data_version,
            )
        ))
    _send_notifications(session_factory, batch, notifier, messages(evaluations, failed=failed))


def _send_notifications(session_factory, batch, notifier, texts):
    for text in texts:
        try:
            sender = notifier if notifier is not None else TelegramNotifier(get_settings())
            sender.send_alert(text)
        except Exception as exc:
            # Telegram URLs contain the token: persist only the exception class, never its text.
            with session_factory() as db:
                db.add(ScheduleError(
                    batch_id=batch, ticker=None, occurred_at=utcnow(),
                    reason=f"Telegram 觀察清單通知失敗（{type(exc).__name__}）",
                ))
                db.commit()


def run_daily_watchlist(
    *, now=None, session_factory=SessionLocal, calendar=None, worker=process_stock, notifier=None
):
    with coordinator_lock(session_factory) as acquired:
        if acquired:
            return _run_daily_watchlist(
                now=now, session_factory=session_factory, calendar=calendar, worker=worker,
                notifier=notifier
            )
