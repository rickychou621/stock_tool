"""Point-in-time signals and next-session fills. No independent strategy logic."""

import math
from dataclasses import asdict
from datetime import date

from app.conditions.types import ConditionBar
from app.market_data.price_adjustment import apply_adjustment
from app.rules.evaluation import RuleEvaluationService
from app.rules.frequency import is_evaluation_day


def metrics(trades: list[dict]) -> dict:
    closed = sorted(
        (t for t in trades if t["status"] == "closed"),
        key=lambda t: (t["exitDate"], t.get("ticker", ""), t["entryDate"]),
    )
    returns = [t["returnRate"] for t in closed]
    n = len(returns)
    if not n:
        return dict(
            tradeCount=0,
            winRate=None,
            averageReturn=None,
            compoundReturn=None,
            maxDrawdown=None,
            profitFactor=None,
            noLosses=False,
            insufficientSample=True,
        )
    equity = peak = 1.0
    drawdown = 0.0
    for value in returns:
        equity *= 1 + value
        peak = max(peak, equity)
        drawdown = max(drawdown, (peak - equity) / peak)
    losses = -sum(value for value in returns if value < 0)
    wins = sum(value for value in returns if value > 0)
    return dict(
        tradeCount=n,
        winRate=sum(r > 0 for r in returns) / n,
        averageReturn=sum(returns) / n,
        compoundReturn=equity - 1,
        maxDrawdown=drawdown,
        profitFactor=wins / losses if losses else None,
        noLosses=losses == 0,
        insufficientSample=n < 10,
    )


def usable(bar) -> bool:
    values = [bar.open, bar.high, bar.low, bar.close]
    return (
        all(math.isfinite(v) and v > 0 for v in values)
        and bar.low <= min(bar.open, bar.close) <= max(bar.open, bar.close) <= bar.high
        and bar.volume > 0
    )


def adjusted_bars(raw, events):
    adjusted = apply_adjustment(raw, events)
    result = [ConditionBar(b.trade_date, **adjusted[b.trade_date], volume=b.volume) for b in raw]
    if any(not usable(b) for b in result):
        raise ValueError("還原價格無效，無法回測")
    return result


def simulate(
    rule,
    ticker: str,
    bars: list[ConditionBar],
    events,
    start: date,
    end: date,
    trading_dates: list[date],
) -> dict:
    frequency = getattr(rule, "evaluation_frequency", "daily")
    # Suspended/invalid sessions cannot generate signals or execute an order.
    valid = [b for b in bars if b.trade_date <= end and usable(b)]
    if not valid:
        raise ValueError("無有效歷史行情")
    events = sorted(
        (e for e in events if e.ex_dividend_date <= end), key=lambda e: e.ex_dividend_date
    )
    # Prices for fills use ONE end-date basis. This does not feed signal decisions.
    execution = {b.trade_date: b for b in adjusted_bars(valid, events)}
    indices = {d: i for i, d in enumerate(trading_dates)}
    trades, signals = [], []
    position = pending = None
    prior = False
    ever_matched = False
    actual_start = actual_end = None
    # Rebuild signal history only when a newly effective dividend changes the basis.
    prefix = []
    effective_events = []
    event_index = 0
    for i, raw in enumerate(valid):
        day = raw.trade_date
        changed = False
        while event_index < len(events) and events[event_index].ex_dividend_date <= day:
            effective_events.append(events[event_index])
            event_index += 1
            changed = True
        if changed:
            prefix = adjusted_bars(valid[: i + 1], effective_events)
        else:
            prefix.append(raw)
        if day < start:
            continue
        # Yesterday's order executes before today's closing signal is evaluated.
        if pending:
            if pending["side"] == "buy":
                position = dict(
                    ticker=ticker,
                    entrySignalDate=pending["date"],
                    entryDate=day.isoformat(),
                    entryPrice=execution[day].open,
                    exitSignalDate=None,
                    exitDate=None,
                    exitPrice=None,
                    status="open",
                    returnRate=None,
                    unrealizedReturn=None,
                    holdingDays=0,
                    valuationDate=None,
                    pendingSide=None,
                )
            else:
                position.update(
                    exitSignalDate=pending["date"],
                    exitDate=day.isoformat(),
                    exitPrice=execution[day].open,
                    status="closed",
                    returnRate=execution[day].open / position["entryPrice"] - 1,
                    holdingDays=indices[day] - indices[date.fromisoformat(position["entryDate"])],
                )
                trades.append(position)
                position = None
            pending = None
        if frequency == "weekly" and not is_evaluation_day(day, frequency):
            continue
        evaluated = RuleEvaluationService.evaluate_bars(rule, ticker, prefix)
        if evaluated.status == "error":
            raise ValueError("；".join(c.reason for c in evaluated.condition_results))
        if not evaluated.condition_results or any(
            not c.data_sufficient for c in evaluated.condition_results
        ):
            if actual_start is not None:
                raise ValueError(f"{day} 回測途中資料不足")
            continue  # New listing: warm up first, disclose the shorter actual period.
        actual_start = actual_start or day
        actual_end = day
        met = evaluated.is_met
        state = (
            ("continued" if prior else ("reentered" if ever_matched else "first"))
            if met
            else ("invalidated" if prior else "not_met")
        )
        signals.append(
            dict(
                date=day.isoformat(),
                state=state,
                isMet=met,
                premiseMet=evaluated.premise_met,
                entryTriggered=evaluated.entry_triggered,
                exitTriggered=evaluated.exit_triggered,
                conditions=[asdict(c) for c in evaluated.condition_results],
            )
        )
        if position is not None:
            should_sell = (
                evaluated.exit_triggered if evaluated.exit_triggered is not None else not met
            )
            if should_sell:
                pending = {"side": "sell", "date": day.isoformat()}
        else:
            should_buy = (
                evaluated.premise_met and evaluated.entry_triggered
                if evaluated.entry_triggered is not None
                else met and not prior
            )
            if should_buy:
                pending = {"side": "buy", "date": day.isoformat()}
        prior = met
        ever_matched = ever_matched or met
    if actual_start is None:
        raise ValueError("歷史資料不足，無法計算所選戰法")
    if position:
        last = valid[-1].trade_date
        position.update(
            unrealizedReturn=execution[last].close / position["entryPrice"] - 1,
            valuationDate=last.isoformat(),
            holdingDays=indices[end] - indices[date.fromisoformat(position["entryDate"])],
            pendingSide=pending["side"] if pending else None,
            exitSignalDate=pending["date"] if pending else None,
        )
        trades.append(position)
    elif pending:
        trades.append(
            dict(
                ticker=ticker,
                entrySignalDate=pending["date"],
                entryDate=None,
                entryPrice=None,
                exitSignalDate=None,
                exitDate=None,
                exitPrice=None,
                status="unfilled",
                returnRate=None,
                unrealizedReturn=None,
                holdingDays=None,
                valuationDate=None,
                pendingSide="buy",
            )
        )
    return dict(
        actualStart=actual_start.isoformat(),
        actualEnd=actual_end.isoformat(),
        requestedStart=start.isoformat(),
        requestedEnd=end.isoformat(),
        priceBasisDate=end.isoformat(),
        trades=trades,
        signals=signals,
        metrics=metrics(trades),
        skippedSessions=sum(1 for d in trading_dates if start <= d <= end and d not in execution),
    )
