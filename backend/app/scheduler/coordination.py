"""MySQL connection lock protects a live batch and makes restart recovery safe."""

from contextlib import contextmanager

from sqlalchemy import text

from app.scheduler.models import ScheduleError, ScheduleRun
from app.scheduler.service import utcnow


@contextmanager
def coordinator_lock(session_factory):
    with session_factory() as db, db.get_bind().connect() as connection:
        mysql = connection.dialect.name == "mysql"
        acquired = (
            not mysql
            or connection.scalar(text("SELECT GET_LOCK('stock_tool_watchlist_schedule', 0)")) == 1
        )
        try:
            yield acquired
        finally:
            if mysql and acquired:
                connection.execute(text("SELECT RELEASE_LOCK('stock_tool_watchlist_schedule')"))


def recover_interrupted(session_factory):
    with coordinator_lock(session_factory) as acquired:
        if not acquired:
            return  # Another process is still working; don't label it interrupted.
        with session_factory() as db:
            run = db.get(ScheduleRun, 1)
            if run and run.status == "running":
                run.status = "failed"
                run.finished_at = utcnow()
                run.failed = run.total - run.succeeded
                db.add(
                    ScheduleError(
                        batch_id=run.batch_id,
                        ticker=None,
                        occurred_at=utcnow(),
                        reason="後端執行中斷，未完成股票不補跑；已完成結果保留。",
                    )
                )
                db.commit()
