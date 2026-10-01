from dataclasses import asdict

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.dependencies import get_db
from app.screening.candidate_service import CandidatePoolService
from app.screening.scan_service import ScreeningScanService
from app.screening.schemas import (
    CandidateRefreshSummarySchema,
    CandidateStockSchema,
    ScanSummarySchema,
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


@router.post("/run", response_model=ScanSummarySchema)
def run_screening_scan(db: Session = Depends(get_db)) -> ScanSummarySchema:
    """手動觸發「排程未來要做的事情」：跑一次全部啟用規則 × 全部股票的評估，
    命中且今天還沒記錄過的寫進alerts_log。排程之後只要定時呼叫同一個
    ScreeningScanService.run_scan()，不需要另外實作。"""
    summary = ScreeningScanService(db).run_scan()
    return ScanSummarySchema(**asdict(summary))
