"""In-process scheduler. Persistent DB claim prevents duplicate daily batches."""

from apscheduler.schedulers.background import BackgroundScheduler

from app.core.db import SessionLocal
from app.market_scan.service import run_daily_market_scan
from app.scheduler.coordination import recover_interrupted
from app.scheduler.daily_jobs import run_daily_watchlist

scheduler = BackgroundScheduler(timezone="Asia/Taipei")


def start_scheduler():
    global scheduler
    recover_interrupted(SessionLocal)
    scheduler = BackgroundScheduler(timezone="Asia/Taipei")
    scheduler.add_job(
        run_daily_watchlist,
        "cron",
        hour=18,
        minute=0,
        id="daily-watchlist",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=30,
    )
    scheduler.add_job(
        run_daily_market_scan,
        "cron",
        hour=19,
        minute=0,
        id="daily-market-scan",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=30,
    )
    scheduler.start()


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=True)
