from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.dependencies import get_db
from app.screening.candidate_service import CandidatePoolService
from app.screening.jobs import ScanBusy, manager
from app.screening.schemas import (
    CandidateRefreshSummarySchema,
    CandidateStockSchema,
    ScanJobSchema,
    ScanJobStartedSchema,
)
from app.screening.service import ScreeningService

router = APIRouter(prefix="/screening", tags=["screening"])


@router.get("/candidates", response_model=list[CandidateStockSchema])
def list_candidates(
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
) -> list[CandidateStockSchema]:
    service = ScreeningService(db)
    return [
        CandidateStockSchema(ticker=c.ticker, reason=c.reason, added_at=c.added_at)
        for c in service.get_candidates(limit)
    ]


@router.post("/candidates/refresh", response_model=CandidateRefreshSummarySchema)
def refresh_candidate_pool(
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
) -> CandidateRefreshSummarySchema:
    """手動觸發候選池粗篩(兩階段篩選的第一階段)。排程之後只要定時呼叫同一個
    CandidatePoolService.refresh()，不需要另外實作。"""
    summary = CandidatePoolService(db).refresh(limit)
    return CandidateRefreshSummarySchema(
        stocks_scanned=summary.stocks_scanned,
        added=summary.added,
        expired=summary.expired,
        active_total=summary.active_total,
    )


@router.post("/run", response_model=ScanJobStartedSchema, status_code=202)
def run_screening_scan() -> ScanJobStartedSchema:
    try:
        return ScanJobStartedSchema(job_id=manager.start())
    except ScanBusy as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/run/latest", response_model=ScanJobSchema | None)
def latest_screening_scan() -> ScanJobSchema | None:
    job = manager.latest()
    return ScanJobSchema(**asdict(job)) if job else None
