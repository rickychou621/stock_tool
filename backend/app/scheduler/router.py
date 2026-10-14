from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.dependencies import get_db
from app.scheduler.models import ScheduleError
from app.scheduler.schemas import ScheduleErrorSchema, ScheduleRunSchema, ScheduleSettingsSchema
from app.scheduler.service import error_schema, latest_run, read_settings, save_settings

router = APIRouter(prefix="/watchlist-schedule", tags=["watchlist-schedule"])


@router.get("/settings", response_model=ScheduleSettingsSchema)
def get_settings(db: Session = Depends(get_db)):
    return read_settings(db)


@router.put("/settings", response_model=ScheduleSettingsSchema)
def put_settings(values: ScheduleSettingsSchema, db: Session = Depends(get_db)):
    try:
        return save_settings(db, values)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/latest", response_model=ScheduleRunSchema | None)
def get_latest(db: Session = Depends(get_db)):
    return latest_run(db)


@router.get("/errors", response_model=list[ScheduleErrorSchema])
def get_errors(
    before_id: int | None = None,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    query = select(ScheduleError).order_by(ScheduleError.id.desc()).limit(limit)
    if before_id is not None:
        query = query.where(ScheduleError.id < before_id)
    return [error_schema(row) for row in db.scalars(query)]
