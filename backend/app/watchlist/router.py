from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.dependencies import get_db
from app.market_data.models import Stock
from app.watchlist.evaluation import WatchlistEvaluationService
from app.watchlist.models import HoldingsWatchlist
from app.watchlist.schemas import (
    EvaluateWatchlistSchema,
    SavedEvaluationSchema,
    WatchlistCreateSchema,
    WatchlistItemSchema,
    WatchlistUpdateSchema,
)
from app.watchlist.service import WatchlistService

router = APIRouter(prefix="/watchlist", tags=["watchlist"])


def _to_schema(item: HoldingsWatchlist, stock: Stock | None = None) -> WatchlistItemSchema:
    return WatchlistItemSchema(
        id=item.id,
        ticker=item.ticker,
        entry_price=float(item.entry_price) if item.entry_price is not None else None,
        entry_date=item.entry_date,
        notes=item.notes,
        is_active=item.is_active,
        stock_name=stock.name if stock else "",
        sector=stock.sector if stock else "",
    )


@router.get("", response_model=list[WatchlistItemSchema])
def list_watchlist(
    limit: int = Query(500, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[WatchlistItemSchema]:
    service = WatchlistService(db)
    items = service.list_active(limit)
    stocks = {
        s.ticker: s
        for s in db.scalars(select(Stock).where(Stock.ticker.in_([i.ticker for i in items])))
    }
    return [_to_schema(item, stocks.get(item.ticker)) for item in items]


@router.post("", response_model=WatchlistItemSchema, status_code=201)
def add_watchlist_item(
    payload: WatchlistCreateSchema,
    db: Session = Depends(get_db),
) -> WatchlistItemSchema:
    service = WatchlistService(db)
    return _to_schema(service.add_holding(payload))


@router.delete("/{item_id}", status_code=204)
def remove_watchlist_item(item_id: int, db: Session = Depends(get_db)) -> None:
    service = WatchlistService(db)
    if service.remove_holding(item_id) is None:
        raise HTTPException(status_code=404, detail="Watchlist item not found")


@router.get("/evaluations", response_model=list[SavedEvaluationSchema])
def list_evaluations(db: Session = Depends(get_db)):
    return WatchlistEvaluationService(db).list_saved()


@router.post("/{item_id}/evaluate", response_model=list[SavedEvaluationSchema])
def evaluate_holding(item_id: int, payload: EvaluateWatchlistSchema, db: Session = Depends(get_db)):
    item = db.get(HoldingsWatchlist, item_id)
    if item is None or not item.is_active:
        raise HTTPException(status_code=404, detail="觀察股票不存在或已移除")
    try:
        return WatchlistEvaluationService(db).evaluate(item, payload.rule_ids)
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch("/{item_id}", response_model=WatchlistItemSchema)
def update_holding(item_id: int, payload: WatchlistUpdateSchema, db: Session = Depends(get_db)):
    item = db.get(HoldingsWatchlist, item_id)
    if item is None or not item.is_active:
        raise HTTPException(status_code=404, detail="觀察股票不存在或已移除")
    stock = db.scalar(select(Stock).where(Stock.ticker == item.ticker))
    if stock is None and payload.sector.strip():
        raise HTTPException(status_code=422, detail="股票尚未建立主檔，無法設定族群")
    changes = payload.model_dump(exclude_unset=True)
    for field in ("entry_price", "entry_date", "notes"):
        if field in changes:
            setattr(item, field, changes[field])
    if stock and "sector" in changes:
        stock.sector = payload.sector.strip()
    db.commit()
    return _to_schema(item, stock)
