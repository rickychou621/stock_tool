from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.rules.models import WatchRule
from app.scheduler.models import ScheduleError, ScheduleRun, ScheduleSettings
from app.scheduler.schemas import ScheduleErrorSchema, ScheduleRunSchema, ScheduleSettingsSchema


def utcnow():
    return datetime.now(UTC).replace(tzinfo=None)


def settings_row(db: Session, *, lock=False):
    row = (
        db.scalar(select(ScheduleSettings).where(ScheduleSettings.id == 1).with_for_update())
        if lock
        else db.get(ScheduleSettings, 1)
    )
    if row is None:
        raise RuntimeError("請先套用 006_watchlist_schedule.sql 遷移")
    return row


def enabled_rule_ids(db: Session):
    return list(db.scalars(select(WatchRule.id).where(WatchRule.is_enabled.is_(True))))


def read_settings(db: Session):
    row = settings_row(db)
    return ScheduleSettingsSchema(
        enabled=row.enabled,
        rule_ids=enabled_rule_ids(db) if row.rule_ids is None else row.rule_ids,
    )


def save_settings(db: Session, values: ScheduleSettingsSchema):
    available = set(enabled_rule_ids(db))
    if not set(values.rule_ids) <= available:
        raise ValueError("選取的戰法已刪除或停用，請重新整理後再儲存。")
    row = settings_row(db, lock=True)
    row.enabled = values.enabled
    row.rule_ids = sorted(set(values.rule_ids))
    db.commit()
    return read_settings(db)


def error_schema(row):
    return ScheduleErrorSchema(
        id=row.id,
        batch_id=row.batch_id,
        ticker=row.ticker,
        occurred_at=row.occurred_at.replace(tzinfo=UTC),
        reason=row.reason,
    )


def latest_run(db: Session):
    row = db.get(ScheduleRun, 1)
    if row is None:
        return None
    errors = list(
        db.scalars(
            select(ScheduleError)
            .where(ScheduleError.batch_id == row.batch_id)
            .order_by(ScheduleError.id)
        )
    )
    return ScheduleRunSchema(
        batch_id=row.batch_id,
        trade_date=row.trade_date,
        started_at=row.started_at.replace(tzinfo=UTC),
        finished_at=row.finished_at.replace(tzinfo=UTC) if row.finished_at else None,
        status=row.status,
        total=row.total,
        succeeded=row.succeeded,
        failed=row.failed,
        errors=[error_schema(error) for error in errors],
    )
