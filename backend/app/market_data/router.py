from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.core.dependencies import get_db
from app.market_data.models import Stock, StockPriceDaily
from app.market_data.schemas import StockSchema
from app.market_data.service import MarketDataService

router = APIRouter(prefix="/stocks", tags=["stocks"])


@router.get("", response_model=list[StockSchema])
def list_stocks(
    limit: int = Query(10, ge=1, le=50),
    chartable_only: bool = True,
    db: Session = Depends(get_db),
) -> list[StockSchema]:
    """預設只回傳已經有日K資料、可以在個股查詢頁畫出線圖的股票；
    傳 chartable_only=false 可以拿到完整股票主檔清單(尚未有其他地方需要用到)。"""
    stmt = select(Stock).where(Stock.is_active.is_(True))
    if chartable_only:
        stmt = stmt.where(exists().where(StockPriceDaily.ticker == Stock.ticker))
    stmt = stmt.order_by(Stock.ticker).limit(limit)
    stocks = db.scalars(stmt).all()
    return [StockSchema(ticker=s.ticker, name=s.name, sector=s.sector) for s in stocks]


@router.post("/{ticker}/sync")
def sync_stock_prices(
    ticker: str,
    days: int = Query(180, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> dict:
    """向FinMind拉近N天的日K股價，upsert進 stock_price_daily。"""
    service = MarketDataService(db)
    rows_synced = service.sync_daily_prices(ticker, days=days)
    return {"ticker": ticker, "rows_synced": rows_synced}


@router.get("/{ticker}", response_model=StockSchema)
def get_stock(ticker: str, db: Session = Depends(get_db)) -> StockSchema:
    stock = db.scalar(select(Stock).where(Stock.ticker == ticker))
    if stock is None:
        raise HTTPException(status_code=404, detail="找不到股票主檔")
    return StockSchema(ticker=stock.ticker, name=stock.name, sector=stock.sector)
