"""Classify one rule evaluation and its previous evaluation day."""

import re
from dataclasses import dataclass

from sqlalchemy import select

from app.conditions.loader import load_condition_bars
from app.core.config import get_settings
from app.market_data.repository import MarketDataRepository
from app.market_scan.models import MarketInstrument
from app.rules.evaluation import RuleEvaluationResult, RuleEvaluationService, missing_friday_result
from app.rules.frequency import last_evaluation_day
from app.rules.protective_stop import protective_stop

ENTRY, HOLD, NEAR_EXIT, EXIT, NONE, NO_DATA, STALE = (
    "ENTRY", "HOLD", "NEAR_EXIT", "EXIT", "NONE", "NO_DATA", "STALE",
)
STATES: tuple[str, ...] = (ENTRY, HOLD, NEAR_EXIT, EXIT, NONE, NO_DATA, STALE)
STATE_LABELS: dict[str, str] = {
    ENTRY: "進場", HOLD: "續抱", NEAR_EXIT: "接近出場", EXIT: "出場",
    NONE: "不符合", NO_DATA: "資料不足", STALE: "需重新評估",
}
URGENCY: dict[str, int] = {
    EXIT: 0, NEAR_EXIT: 1, ENTRY: 2, HOLD: 3, STALE: 4, NO_DATA: 5, NONE: 6,
}


@dataclass
class RuleState:
    state: str
    reason: str
    trigger_price: float | None
    close: float | None
    distance_pct: float | None
    ma_distance_pct: float | None = None
    ma_slope_pct: float | None = None


def _triggered(result):
    if result.entry_triggered is not None:
        return result.premise_met and result.entry_triggered
    return result.is_met


_REQUIRED_BARS = re.compile(r"^(.+資料不足)：需要 (\d+) 根")


def _missing_reason(result):
    missing = [c.reason for c in result.condition_results if not c.data_sufficient]
    if not missing:
        missing = [c.reason for c in result.condition_results if not c.is_met]
    # Same timeframe shortage: keep only the condition that needs the most bars.
    kept: dict[str, tuple[int, str]] = {}
    for reason in missing:
        match = _REQUIRED_BARS.match(reason)
        key, need = (match.group(1), int(match.group(2))) if match else (reason, 0)
        if key not in kept or need > kept[key][0]:
            kept[key] = (need, reason)
    return "；".join(reason for _, reason in kept.values()) or "無可用的評估資料"


def classify(rule, ticker, bars, result=None, *, kind="stock", near_exit_pct=None) -> RuleState:
    if not bars:
        return RuleState(NO_DATA, "尚無行情資料", None, None, None)
    if result is None:
        result = RuleEvaluationService.evaluate_bars(rule, ticker, bars)

    stop = protective_stop(result, kind)
    price = stop["price"] if stop else None
    close = stop["close"] if stop else None
    distance = (close - price) / price if price is not None and close is not None else None

    def indicator_pct(condition_id, key, digits):
        value = next(
            (c.indicators.get(key) for c in result.condition_results
             if c.condition_id == condition_id and c.indicators),
            None,
        )
        return round(value * 100, digits) if value is not None else None

    def outcome(state, reason):
        return RuleState(
            state, reason, price, close, round(distance * 100, 1) if distance is not None else None,
            ma_distance_pct=indicator_pct("ma_touch_rebound", "close_distance_pct", 1),
            ma_slope_pct=indicator_pct("ma_rising", "slope_pct", 2),
        )

    def reasons(role):
        return "；".join(c.reason for c in result.condition_results if c.role == role and c.is_met)

    if result.status in ("error", "insufficient_data"):
        return outcome(NO_DATA, _missing_reason(result))
    if result.exit_triggered is True:
        return outcome(EXIT, reasons("exit"))
    if _triggered(result):
        previous_bars = bars[:-1]
        if getattr(rule, "evaluation_frequency", "daily") == "weekly":
            previous_day = (
                last_evaluation_day(bars[-2].trade_date, [b.trade_date for b in bars], "weekly")
                if len(bars) > 1 else None
            )
            if previous_day is None:
                return outcome(NO_DATA, "前一個有效交易日資料不足：尚無週五判斷資料")
            previous_bars = [b for b in bars if b.trade_date <= previous_day]
        if not previous_bars:
            return outcome(NO_DATA, "前一個有效交易日資料不足：尚無行情資料")
        previous = RuleEvaluationService.evaluate_bars(rule, ticker, previous_bars)
        if previous.status in ("error", "insufficient_data") or any(
            not c.data_sufficient for c in previous.condition_results
        ):
            return outcome(NO_DATA, "前一個有效交易日資料不足：" + _missing_reason(previous))
        if not _triggered(previous):
            return outcome(ENTRY, "｜".join(
                c.reason for role in ("entry", "premise")
                for c in result.condition_results if c.role == role
            ))
    if near_exit_pct is None:
        near_exit_pct = get_settings().near_exit_pct
    if result.premise_met and distance is not None and distance <= near_exit_pct:
        return outcome(NEAR_EXIT, f"收盤距觸價 {distance * 100:.1f}%")
    if result.premise_met:
        if result.entry_triggered is None:
            return outcome(HOLD, reasons("premise"))
        return outcome(HOLD, "｜".join(
            c.reason for role in ("premise", "entry")
            for c in result.condition_results
            if c.role == role and (role == "premise" or not c.is_met)
        ))
    return outcome(NONE, next(
        (c.reason for c in result.condition_results if c.role == "premise" and not c.is_met), "",
    ))


def instrument_kind(db, ticker) -> str:
    return db.scalar(
        select(MarketInstrument.kind).where(MarketInstrument.ticker == ticker)
    ) or "stock"


def evaluate_with_state(
    db, rule, ticker, *, kind="stock",
) -> tuple[RuleEvaluationResult, RuleState]:
    bars = load_condition_bars(MarketDataRepository(db), ticker)
    if rule.evaluation_frequency == "weekly":
        cutoff = (
            last_evaluation_day(bars[-1].trade_date, [b.trade_date for b in bars], "weekly")
            if bars else None
        )
        if cutoff is None:
            return missing_friday_result(rule, ticker), RuleState(
                NO_DATA, "尚無週五判斷資料", None, None, None,
            )
        bars = [bar for bar in bars if bar.trade_date <= cutoff]
    result = RuleEvaluationService.evaluate_bars(rule, ticker, bars)
    return result, classify(rule, ticker, bars, result=result, kind=kind)
