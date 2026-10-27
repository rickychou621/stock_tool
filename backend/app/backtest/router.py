from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import Field
from sqlalchemy.orm import Session

from app.backtest.models import BacktestResult, BacktestTask
from app.backtest.service import BacktestBusy, build_equity_curve, manager, read_report
from app.core.dependencies import get_db
from app.core.schemas import CamelModel

router = APIRouter(prefix="/backtests", tags=["backtests"])


class StartBacktest(CamelModel):
    rule_ids: list[int] = Field(min_length=1, max_length=50)


@router.post("", status_code=202)
def start_backtest(values: StartBacktest):
    try:
        return {"batchId": manager.start(values.rule_ids)}
    except BacktestBusy as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/latest")
def latest(db: Session = Depends(get_db)):
    return read_report(db)


@router.get("/results/{result_id}")
def detail(
    result_id: int,
    expected_batch_id: str | None = Query(None, alias="expectedBatchId"),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    row = db.get(BacktestResult, result_id)
    if row is None:
        raise HTTPException(404, "找不到回測結果")
    if expected_batch_id is not None and row.batch_id != expected_batch_id:
        raise HTTPException(409, "結果已更新，請重新整理後查看明細")
    payload = row.payload
    task = db.get(BacktestTask, 1)
    benchmark = (task.context_json or {}).get("benchmark", {}) if task else {}
    return dict(
        equityCurve=build_equity_curve(
            payload["trades"], row.summary["actualStart"], row.summary["actualEnd"], benchmark,
        ),
        tradeMarkers=[
            {"date": day, "side": side}
            for trade in payload["trades"]
            for day, side in (
                (trade.get("entryDate") if trade["status"] != "unfilled" else None, "buy"),
                (trade.get("exitDate") if trade["status"] == "closed" else None, "sell"),
            )
            if day is not None
        ],
        needsRerun=payload.get("schemaVersion") != 2,
        costSnapshot=payload.get("costSnapshot"),
        warnings=payload.get("warnings", []),
        benchmarkReason=payload.get("benchmarkReason"),
        batchId=row.batch_id,
        stale=row.stale,
        definition=payload["definition"],
        priceBasisDate=payload["priceBasisDate"],
        tradeTotal=len(payload["trades"]),
        trades=payload["trades"][offset : offset + limit],
        signalTotal=len(payload["signals"]),
        signals=payload["signals"][offset : offset + limit],
    )
