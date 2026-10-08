"""Persist one latest result per holding/rule; all decisions use the shared engine."""

import hashlib
import json
from dataclasses import asdict
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.market_data.models import Stock
from app.market_data.service import MarketDataService
from app.rules.evaluation import RuleEvaluationService
from app.rules.models import WatchRule
from app.rules.preparation import PreparationError, history_days
from app.rules.schemas import RuleEvaluationSchema
from app.watchlist.models import HoldingsWatchlist, WatchlistEvaluation
from app.watchlist.schemas import SavedEvaluationSchema


def fingerprint(rule: WatchRule) -> str:
    definition = {
        "operator": rule.logic_operator,
        "conditions": [
            [c.condition_id, c.params, c.sort_order]
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
        return [self._schema(saved, stock, rule) for saved, stock, rule in rows]

    @staticmethod
    def _schema(saved, stock, rule):
        return SavedEvaluationSchema(
            item_id=saved.item_id,
            rule_id=rule.id,
            rule_name=rule.name,
            result=saved.result,
            evaluated_at=saved.evaluated_at.replace(tzinfo=UTC),
            stale=saved.data_version != stock.data_version
            or saved.rule_fingerprint != fingerprint(rule),
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
        engine = RuleEvaluationService(self._db)
        for rule in rules:
            result = None
            failure = error
            if failure is None:
                try:
                    result = RuleEvaluationSchema(**asdict(engine.evaluate(rule, item.ticker)))
                except (ValueError, TypeError, ArithmeticError, KeyError):
                    failure = "評估失敗，請檢查戰法設定後重試。"
            if result is None:
                result = RuleEvaluationSchema(
                    rule_id=rule.id,
                    ticker=item.ticker,
                    is_met=False,
                    logic_operator=rule.logic_operator,
                    status="error",
                    data_date=None,
                    condition_results=[
                        dict(
                            condition_id="evaluation",
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
            output.append(self._schema(saved, stock, rule))
        return output
