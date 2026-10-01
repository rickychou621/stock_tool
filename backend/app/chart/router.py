from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.chart.schemas import PriceBarSchema
from app.chart.service import ChartService
from app.core.dependencies import get_db

router = APIRouter(prefix="/chart", tags=["chart"])


@router.get("/{ticker}", response_model=list[PriceBarSchema])
def get_price_history(
    ticker: str,
    limit: int = Query(120, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[PriceBarSchema]:
    service = ChartService(db)
    bars = service.get_price_history(ticker, limit)
    return [
        PriceBarSchema(
            date=bar.trade_date,
            # 優先用還原股價；還沒算過還原股價的舊資料(adj_*為NULL)才退回原始股價。
            open=float(bar.adj_open if bar.adj_open is not None else bar.open),
            high=float(bar.adj_high if bar.adj_high is not None else bar.high),
            low=float(bar.adj_low if bar.adj_low is not None else bar.low),
            close=float(bar.adj_close if bar.adj_close is not None else bar.close),
            volume=bar.volume,
        )
        for bar in bars
    ]
