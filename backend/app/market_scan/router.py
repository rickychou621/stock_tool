from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.dependencies import get_db
from app.core.schemas import CamelModel
from app.market_scan.models import (
    CandidateIndicator,
    ScanCandidate,
    ScanError,
    ScanPublication,
    ScanTask,
)
from app.market_scan.schemas import (
    Accepted,
    CandidateResponse,
    ErrorResponse,
    PageResponse,
    SettingsResponse,
    SummaryResponse,
    TasksResponse,
)
from app.market_scan.service import ScanBusy, chosen_rules, manager, settings_row

router = APIRouter(prefix="/market-scan", tags=["market-scan"])


class SettingsInput(CamelModel):
    enabled: bool
    rule_ids: list[int] = Field(max_length=50)


class StartInput(CamelModel):
    rule_ids: list[int] | None = Field(default=None, max_length=50)


def iso(value):
    return value.isoformat() + "Z" if value else None


def read_settings(db):
    row = settings_row(db)
    active = chosen_rules(db)
    selected = [r.id for r in active if row.rule_ids is None or r.id in row.rule_ids]
    return dict(
        enabled=row.enabled,
        ruleIds=selected,
        workers=manager.settings.market_scan_workers,
        requestsPerMinute=manager.settings.finmind_scan_requests_per_minute,
    )


@router.get("/settings", response_model=SettingsResponse)
def settings(db: Session = Depends(get_db)):
    return read_settings(db)


@router.put("/settings", response_model=SettingsResponse)
def save(values: SettingsInput, db: Session = Depends(get_db)):
    try:
        chosen_rules(db, values.rule_ids)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    row = settings_row(db)
    row.enabled, row.rule_ids = values.enabled, list(dict.fromkeys(values.rule_ids))
    db.commit()
    return read_settings(db)


def start(values, kind):
    try:
        return dict(batchId=manager.start(values.rule_ids, kind=kind))
    except ScanBusy as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/initialize", status_code=202, response_model=Accepted)
def initialize(values: StartInput):
    return start(values, "initialize")


@router.post("/run", status_code=202, response_model=Accepted)
def run(values: StartInput):
    return start(values, "scan")


def task_json(t):
    return (
        dict(
            kind=t.kind,
            batchId=t.batch_id,
            source=t.source,
            status=t.status,
            startedAt=iso(t.started_at),
            finishedAt=iso(t.finished_at),
            baseline=t.baseline,
            rules=t.rules,
            total=t.total,
            processed=t.processed,
            succeeded=t.succeeded,
            failed=t.failed,
            insufficient=t.insufficient,
            warnings=t.warnings,
        )
        if t
        else None
    )


@router.get("/tasks", response_model=TasksResponse)
def tasks(db: Session = Depends(get_db)):
    return dict(
        scan=task_json(db.get(ScanTask, "scan")),
        initialize=task_json(db.get(ScanTask, "initialize")),
    )


@router.get("/summary", response_model=SummaryResponse | None)
def summary(db: Session = Depends(get_db)):
    row = db.get(ScanPublication, 1)
    return row.metadata_json if row else None


@router.get("/errors", response_model=PageResponse[ErrorResponse])
def errors(
    kind: Literal["scan", "initialize"] = "scan",
    page: int = Query(1, ge=1, le=10000),
    page_size: int = Query(50, alias="pageSize", ge=1, le=200),
    db: Session = Depends(get_db),
):
    condition = ScanError.kind == kind
    total = db.scalar(select(func.count()).select_from(ScanError).where(condition))
    rows = db.scalars(
        select(ScanError)
        .where(condition)
        .order_by(ScanError.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return dict(
        total=total,
        page=page,
        pageSize=page_size,
        items=[
            dict(ticker=r.ticker, ruleId=r.rule_id, status=r.status, reason=r.reason) for r in rows
        ],
    )


@router.get("/indicators", response_model=list[str])
def indicator_names(db: Session = Depends(get_db)):
    return list(
        db.scalars(select(CandidateIndicator.name).distinct().order_by(CandidateIndicator.name))
    )


@router.get("/candidates", response_model=PageResponse[CandidateResponse])
def candidates(
    page: int = Query(1, ge=1, le=10000),
    page_size: int = Query(50, alias="pageSize", ge=1, le=200),
    search: str = Query("", max_length=100),
    kind: Literal["stock", "etf"] | None = None,
    rule_id: int | None = Query(None, alias="ruleId", ge=1),
    price_date: Annotated[date | None, Query(alias="priceDate")] = None,
    min_price: float | None = Query(None, alias="minPrice", ge=0, allow_inf_nan=False),
    max_price: float | None = Query(None, alias="maxPrice", ge=0, allow_inf_nan=False),
    min_volume: int | None = Query(None, alias="minVolume", ge=0),
    min_turnover: float | None = Query(None, alias="minTurnover", ge=0, allow_inf_nan=False),
    indicator: str | None = Query(None, max_length=120),
    indicator_min: float | None = Query(None, alias="indicatorMin", allow_inf_nan=False),
    indicator_max: float | None = Query(None, alias="indicatorMax", allow_inf_nan=False),
    status: Literal["normal", "stale", "insufficient_history", "all"] = "normal",
    sort: Literal[
        "ticker",
        "stockName",
        "kind",
        "ruleId",
        "close",
        "priceDate",
        "volume",
        "turnover",
        "scannedAt",
        "status",
        "indicator",
    ] = "ticker",
    direction: Literal["asc", "desc"] = "asc",
    db: Session = Depends(get_db),
):
    c = ScanCandidate
    filters = []
    if status != "all":
        filters.append(c.status == status)
    if search:
        escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        filters.append(
            or_(
                c.ticker.like(f"%{escaped}%", escape="\\"),
                c.stock_name.like(f"%{escaped}%", escape="\\"),
            )
        )
    if kind:
        filters.append(c.kind == kind)
    for column, value, op in [
        (c.rule_id, rule_id, "eq"),
        (c.price_date, price_date, "eq"),
        (c.close, min_price, "ge"),
        (c.close, max_price, "le"),
        (c.volume, min_volume, "ge"),
        (c.turnover, min_turnover, "ge"),
    ]:
        if value is not None:
            filters.append(getattr(column, "__" + op + "__")(value))
    query = select(c)
    order = {
        "ticker": c.ticker,
        "stockName": c.stock_name,
        "kind": c.kind,
        "ruleId": c.rule_id,
        "close": c.close,
        "priceDate": c.price_date,
        "volume": c.volume,
        "turnover": c.turnover,
        "scannedAt": c.scanned_at,
        "status": c.status,
    }
    if indicator:
        query = query.join(CandidateIndicator, CandidateIndicator.candidate_id == c.id)
        filters.append(CandidateIndicator.name == indicator)
        if indicator_min is not None:
            filters.append(CandidateIndicator.value >= indicator_min)
        if indicator_max is not None:
            filters.append(CandidateIndicator.value <= indicator_max)
        order["indicator"] = CandidateIndicator.value
    elif sort == "indicator" or indicator_min is not None or indicator_max is not None:
        raise HTTPException(422, "請先選擇技術指標")
    if min_price is not None and max_price is not None and min_price > max_price:
        raise HTTPException(422, "價格範圍錯誤")
    if indicator_min is not None and indicator_max is not None and indicator_min > indicator_max:
        raise HTTPException(422, "指標範圍錯誤")
    query = query.where(*filters)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    ordering = order[sort]
    rows = db.scalars(
        query.order_by(
            ordering.is_(None), ordering.desc() if direction == "desc" else ordering.asc(), c.id
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return dict(
        total=total,
        page=page,
        pageSize=page_size,
        items=[
            dict(
                id=r.id,
                ticker=r.ticker,
                stockName=r.stock_name,
                kind=r.kind,
                ruleId=r.rule_id,
                ruleName=r.rule_name,
                batchId=r.batch_id,
                status=r.status,
                statusReason=r.status_reason,
                reason=r.reason,
                indicators=r.indicators,
                close=float(r.close),
                priceDate=r.price_date,
                volume=r.volume,
                turnover=float(r.turnover) if r.turnover is not None else None,
                scannedAt=iso(r.scanned_at),
                olderQuote=r.older_quote,
            )
            for r in rows
        ],
    )
