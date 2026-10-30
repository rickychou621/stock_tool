"""Persist one latest result per holding/rule; all decisions use the shared engine."""

import hashlib
import json
from dataclasses import asdict
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.market_data.models import Stock
from app.market_data.service import MarketDataService
from app.rules.freshness import expected_data_date, latest_trading_days
from app.rules.models import WatchRule
from app.rules.preparation import PreparationError, history_days
from app.rules.protective_stop import protective_stop
from app.rules.schemas import RuleEvaluationSchema
from app.rules.state import NO_DATA, RuleState, evaluate_with_state, instrument_kind
from app.watchlist.models import HoldingsWatchlist, WatchlistEvaluation
from app.watchlist.schemas import SavedEvaluationSchema


def fingerprint(rule: WatchRule) -> str:
    definition = {
        "operator": rule.logic_operator,
        "evaluation_frequency": getattr(rule, "evaluation_frequency", None) or "daily",
        "conditions": [
            [c.condition_id, c.params, c.sort_order, getattr(c, "role", None) or "premise"]
            for c in sorted(rule.conditions, key=lambda c: c.sort_order)
        ],
    }
    if any(c.condition_id == "bollinger_mid_up" for c in rule.conditions):
        definition["bollinger_revision"] = 2
    return hashlib.sha256(json.dumps(definition, sort_keys=True).encode()).hexdigest()


class WatchlistEvaluationService:
    def __init__(self, db: Session):
        self._db = db

    def list_saved(self) -> list[SavedEvaluationSchema]:
        rows = self._db.execute(
            select(WatchlistEvaluation, Stock, WatchRule)
            .join(HoldingsWatchlist, HoldingsWatchlist.id == WatchlistEvaluation.item_id)
            .join(Stock, Stock.ticker == HoldingsWatchlist.ticker)
            .join(WatchRule, WatchRule.id == WatchlistEvaluation.rule_id)
            .options(selectinload(WatchRule.conditions))
            .where(HoldingsWatchlist.is_active.is_(True))
            .limit(25000)
        ).all()
        latest, trading_days = latest_trading_days(self._db)
        return [self._schema(saved, stock, rule, latest, trading_days)
                for saved, stock, rule in rows]

    @staticmethod
    def _schema(saved, stock, rule, latest, trading_days):
        expected = expected_data_date(latest, trading_days, rule.evaluation_frequency)
        data_date = saved.result.get("dataDate")
        market_data_stale = bool(
            data_date and expected and date.fromisoformat(data_date) < expected
        )
        stale = (
            saved.data_version != stock.data_version
            or saved.rule_fingerprint != fingerprint(rule)
        )
        return SavedEvaluationSchema(
            item_id=saved.item_id,
            rule_id=rule.id,
            rule_name=rule.name,
            evaluation_frequency=rule.evaluation_frequency,
            result=saved.result,
            evaluated_at=saved.evaluated_at.replace(tzinfo=UTC),
            stale=stale,
            expected_data_date=expected,
            market_data_stale=market_data_stale,
            state=(
                "STALE" if stale or not saved.result.get("state")
                else saved.result["state"]["state"]
            ),
        )

    def evaluate(self, item: HoldingsWatchlist, rule_ids: list[int]):
        rules = list(
            self._db.scalars(
                select(WatchRule)
                .options(selectinload(WatchRule.conditions))
                .where(WatchRule.id.in_(set(rule_ids)))
                .order_by(WatchRule.id)
            )
        )
        if len(rules) != len(set(rule_ids)):
            raise ValueError("選取的戰法已刪除，請重新整理後再試。")
        stock = self._db.scalar(select(Stock).where(Stock.ticker == item.ticker))
        if stock is None:
            raise ValueError("股票尚未建立主檔，無法更新行情。")
        days = max(history_days(rule) for rule in rules)
        error = None
        try:
            if MarketDataService(self._db).sync_daily_prices(item.ticker, days=days) == 0:
                raise PreparationError("資料來源未回傳行情")
        except Exception:
            self._db.rollback()
            error = "行情更新失敗，本次未評估；請稍後重試。"
        self._db.refresh(stock)
        version = stock.data_version
        output = []
        latest, trading_days = latest_trading_days(self._db)
        kind = instrument_kind(self._db, item.ticker)
        for rule in rules:
            result = None
            failure = error
            if failure is None:
                try:
                    evaluated, state = evaluate_with_state(
                        self._db, rule, item.ticker, kind=kind,
                    )
                    result = RuleEvaluationSchema(
                        **asdict(evaluated), state=asdict(state),
                        protective_stop=protective_stop(evaluated, kind)
                    )
                except (ValueError, TypeError, ArithmeticError, KeyError):
                    failure = "評估失敗，請檢查戰法設定後重試。"
            if result is None:
                result = RuleEvaluationSchema(
                    evaluation_frequency=rule.evaluation_frequency,
                    rule_id=rule.id,
                    ticker=item.ticker,
                    is_met=False,
                    premise_met=False,
                    entry_triggered=None,
                    exit_triggered=None,
                    logic_operator=rule.logic_operator,
                    status="error",
                    state=asdict(RuleState(NO_DATA, failure, None, None, None)),
                    data_date=None,
                    condition_results=[
                        dict(
                            condition_id="evaluation",
                            role="premise",
                            is_met=False,
                            reason=failure,
                            data_sufficient=False,
                        )
                    ],
                )
            rule_fingerprint = fingerprint(rule)
            saved = self._db.scalar(
                select(WatchlistEvaluation).where(
                    WatchlistEvaluation.item_id == item.id,
                    WatchlistEvaluation.rule_id == rule.id,
                )
            )
            if saved is None:
                saved = WatchlistEvaluation(item_id=item.id, rule_id=rule.id)
                self._db.add(saved)
            saved.result = result.model_dump(mode="json", by_alias=True)
            saved.evaluated_at = datetime.now(UTC).replace(tzinfo=None)
            saved.data_version = version
            saved.rule_fingerprint = rule_fingerprint
            self._db.commit()
            output.append(self._schema(saved, stock, rule, latest, trading_days))
        return output
