"""規則評估引擎：輸入一條規則+一檔股票，回傳現在符不符合。

這是唯一「真正跑戰法邏輯」的地方 —— 不管是API被動呼叫、還是之後排程主動觸發，
都應該呼叫這個service，不要在別的地方複製一份判斷邏輯。"""

from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from app.conditions.loader import load_condition_bars
from app.conditions.registry import get_condition
from app.market_data.repository import MarketDataRepository
from app.rules.models import WatchRule


@dataclass
class ConditionEvaluation:
    condition_id: str
    is_met: bool
    reason: str
    data_sufficient: bool = True
    upper_band_status: str | None = None


@dataclass
class RuleEvaluationResult:
    rule_id: int
    ticker: str
    is_met: bool
    logic_operator: str
    condition_results: list[ConditionEvaluation]
    status: str = "not_met"
    data_date: date | None = None


class RuleEvaluationService:
    def __init__(self, db: Session) -> None:
        self._market_data_repository = MarketDataRepository(db)

    def evaluate(self, rule: WatchRule, ticker: str) -> RuleEvaluationResult:
        bars = load_condition_bars(self._market_data_repository, ticker)

        condition_results: list[ConditionEvaluation] = []
        has_error = False
        for rule_condition in sorted(rule.conditions, key=lambda c: c.sort_order):
            try:
                condition_cls = get_condition(rule_condition.condition_id)
            except KeyError:
                has_error = True
                condition_results.append(
                    ConditionEvaluation(rule_condition.condition_id, False, "找不到這個條件的實作")
                )
                continue

            result = condition_cls().evaluate(bars, rule_condition.params)
            condition_results.append(
                ConditionEvaluation(
                    rule_condition.condition_id,
                    result.is_met,
                    result.reason,
                    result.data_sufficient,
                    result.upper_band_status,
                )
            )

        if rule.logic_operator == "OR":
            is_met = any(c.is_met for c in condition_results)
        else:
            is_met = bool(condition_results) and all(c.is_met for c in condition_results)

        status = "matched" if is_met else "not_met"
        if not is_met and any(not c.data_sufficient for c in condition_results):
            status = "insufficient_data"
        if has_error:
            status = "error"
            is_met = False

        return RuleEvaluationResult(
            rule_id=rule.id,
            ticker=ticker,
            is_met=is_met,
            logic_operator=rule.logic_operator,
            condition_results=condition_results,
            status=status,
            data_date=bars[-1].trade_date if bars else None,
        )
