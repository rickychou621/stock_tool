"""Read-only signal history and grouped forward performance."""

from datetime import date
from statistics import mean, median
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.dependencies import get_db
from app.market_scan.models import SignalHistory, SignalReturn, SignalTrackingMeta

router = APIRouter()


def filters(
    rule_id: int | None = Query(None, alias="ruleId", ge=1),
    start: Annotated[date | None, Query(alias="from")] = None,
    end: Annotated[date | None, Query(alias="to")] = None,
    kind: Literal["stock", "etf"] | None = None,
    min_turnover: float | None = Query(None, alias="minTurnover", ge=0, allow_inf_nan=False),
    exclude_older_quote: bool = Query(False, alias="excludeOlderQuote"),
):
    if start and end and start > end:
        raise HTTPException(422, "起始日期不可晚於結束日期")
    conditions = []
    for column, value, op in (
        (SignalHistory.rule_id, rule_id, "eq"),
        (SignalHistory.signal_date, start, "ge"),
        (SignalHistory.signal_date, end, "le"),
        (SignalHistory.kind, kind, "eq"),
        (SignalHistory.turnover, min_turnover, "ge"),
    ):
        if value is not None:
            conditions.append(getattr(column, "__" + op + "__")(value))
    if exclude_older_quote:
        conditions.append(SignalHistory.older_quote.is_(False))
    return conditions


@router.get("/signal-performance")
def performance(conditions=Depends(filters), db: Session = Depends(get_db)):
    rows = db.execute(
        select(
            SignalHistory.rule_id,
            SignalHistory.rule_name,
            SignalReturn.horizon,
            SignalReturn.status,
            SignalReturn.values_json,
        )
        .join(SignalReturn, SignalReturn.signal_id == SignalHistory.id)
        .where(*conditions)
        .order_by(SignalHistory.signal_date, SignalHistory.id)
    )
    groups = {}
    for rid, name, horizon, status, values in rows:
        group = groups.setdefault(
            (rid, horizon),
            dict(ruleId=rid, ruleName=name, horizon=horizon, pending=0, unavailable=0, values=[]),
        )
        group["ruleName"] = name
        if status == "completed":
            group["values"].append(values)
        else:
            group[status] += 1
    result = []
    for _, group in sorted(groups.items()):
        values = group.pop("values")
        n = len(values)
        net = [v["netReturn"] for v in values]
        excess = [v["excessReturn"] for v in values]
        result.append(
            dict(
                **group,
                sampleCount=n,
                sampleInsufficient=n < 30,
                winRate=sum(v > 0 for v in net) / n if n else None,
                averageNetReturn=mean(net) if n else None,
                medianNetReturn=median(net) if n else None,
                averageExcessReturn=mean(excess) if n else None,
                positiveExcessRate=sum(v > 0 for v in excess) / n if n else None,
                averageMaxAdverseReturn=mean(v["maxAdverseReturn"] for v in values) if n else None,
            )
        )
    meta = db.get(SignalTrackingMeta, 1)
    return dict(deployedOn=meta.deployed_on if meta else None, groups=result)


@router.get("/signals")
def signals(
    conditions=Depends(filters),
    ticker: str | None = Query(None, max_length=10),
    signal_date: Annotated[date | None, Query(alias="signalDate")] = None,
    page: int = Query(1, ge=1, le=10000),
    page_size: int = Query(50, alias="pageSize", ge=1, le=200),
    db: Session = Depends(get_db),
):
    conditions = list(conditions)
    if ticker:
        conditions.append(SignalHistory.ticker == ticker)
    if signal_date:
        conditions.append(SignalHistory.signal_date == signal_date)
    total = db.scalar(select(func.count()).select_from(SignalHistory).where(*conditions))
    rows = list(
        db.scalars(
            select(SignalHistory)
            .where(*conditions)
            .order_by(SignalHistory.signal_date.desc(), SignalHistory.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    returns = {}
    for r in db.scalars(
        select(SignalReturn)
        .where(SignalReturn.signal_id.in_([s.id for s in rows]))
        .order_by(SignalReturn.horizon)
    ):
        values = {
            k: None
            for k in (
                "entryDate",
                "entryPrice",
                "dueDate",
                "valuationDate",
                "exitPrice",
                "grossReturn",
                "netReturn",
                "benchmarkReturn",
                "excessReturn",
                "maxAdverseReturn",
            )
        }
        returns.setdefault(r.signal_id, []).append(
            dict(horizon=r.horizon, status=r.status, reason=r.reason, **{**values, **r.values_json})
        )
    return dict(
        total=total,
        page=page,
        pageSize=page_size,
        items=[
            dict(
                id=s.id,
                signalDate=s.signal_date,
                ticker=s.ticker,
                stockName=s.stock_name,
                ruleId=s.rule_id,
                ruleName=s.rule_name,
                kind=s.kind,
                priceDate=s.price_date,
                olderQuote=s.older_quote,
                close=float(s.close),
                volume=s.volume,
                turnover=float(s.turnover) if s.turnover is not None else None,
                indicators=s.indicators,
                source=s.source,
                firstBatchId=s.first_batch_id,
                lastBatchId=s.last_batch_id,
                createdAt=s.created_at.isoformat() + "Z",
                lastSeenAt=s.last_seen_at.isoformat() + "Z",
                costSnapshot=s.cost_snapshot,
                returns=returns.get(s.id, []),
            )
            for s in rows
        ],
    )
