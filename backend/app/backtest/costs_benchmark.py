"""Enrich simulated trades without changing signals or order execution."""

from sqlalchemy import select

from app.backtest.data import prepare_data
from app.backtest.simulation import adjusted_bars, metrics, usable
from app.market_data.models import Stock
from app.trading_costs import TradingCosts


def load_benchmark(factory, start, end, dates):
    try:
        with factory() as db:
            if db.scalar(select(Stock).where(Stock.ticker == "0050")) is None:
                db.add(Stock(ticker="0050", name="元大台灣50", market="上市"))
                db.commit()
            raw, events = prepare_data(db, "0050", start, end, dates)
            valid = [b for b in raw if usable(b)]
            adjusted = adjusted_bars(valid, events) if valid else []
            return {b.trade_date.isoformat(): {"open": b.open, "close": b.close} for b in adjusted}
    except Exception:
        # Benchmark availability cannot abort strategy backtests or expose credentials.
        return {}


def benchmark_return(bars, start, end, exit_field="open"):
    if not start or not end or start not in bars or end not in bars:
        return None
    return bars[end][exit_field] / bars[start]["open"] - 1


def enrich(payload, costs, kind, benchmark):
    costs = TradingCosts.from_snapshot(costs)
    warnings = []
    if kind not in ("stock", "etf"):
        kind = "stock"
        warnings.append("查無標的種類，證交稅採普通股費率")
    for trade in payload["trades"]:
        gross = trade.get("returnRate")
        unrealized = trade.get("unrealizedReturn")
        net = costs.net_return(1, 1 + gross, kind) if gross is not None else None
        net_unrealized = (
            costs.net_return(1, 1 + unrealized, kind) if unrealized is not None else None
        )
        base = benchmark_return(benchmark, trade.get("entryDate"), trade.get("exitDate"))
        trade.update(
            grossReturnRate=gross,
            netReturnRate=net,
            returnRate=net,
            grossUnrealizedReturn=unrealized,
            netUnrealizedReturn=net_unrealized,
            unrealizedReturn=net_unrealized,
            benchmarkReturn=base,
            excessReturn=net - base if net is not None and base is not None else None,
            benchmarkReason=None if base is not None else "0050 同日行情不足或交易尚未平倉",
        )
    closed = [t for t in payload["trades"] if t["status"] == "closed"]
    excess = [t["excessReturn"] for t in closed if t["excessReturn"] is not None]
    hold = benchmark_return(benchmark, payload["actualStart"], payload["actualEnd"], "close")
    payload.update(
        schemaVersion=2,
        costSnapshot=costs.snapshot(),
        instrumentKind=kind,
        warnings=warnings,
        metrics=metrics(payload["trades"]),
        grossMetrics=metrics(
            [{**t, "returnRate": t["grossReturnRate"]} for t in payload["trades"]]
        ),
        averageExcessReturn=sum(excess) / len(excess) if excess else None,
        benchmarkTradeCount=len(excess),
        benchmarkBuyHoldReturn=hold,
        benchmarkReason=None if hold is not None else "0050 實際期間起訖日行情不足",
    )
    return payload
