"""One stock per independent session; retain valid results when preparation fails."""

import math
from dataclasses import asdict
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.market_data.models import Stock
from app.market_data.repository import MarketDataRepository
from app.market_data.service import MarketDataService
from app.market_data.validation import is_no_trade
from app.rules.models import WatchRule
from app.rules.preparation import history_days
from app.rules.protective_stop import protective_stop
from app.rules.schemas import RuleEvaluationSchema
from app.rules.state import evaluate_with_state, instrument_kind
from app.scheduler.service import utcnow
from app.watchlist.evaluation import fingerprint
from app.watchlist.models import HoldingsWatchlist, WatchlistEvaluation


def validate_bars(bars, day: date):
    if not bars or bars[-1].trade_date != day or is_no_trade(bars[-1]):
        raise ValueError(f"最新日K不是本次交易日 {day}，可能尚未更新或個股停牌")
    for bar in bars:
        if is_no_trade(bar):
            continue
        for prefix in ("", "adj_"):
            prices = [getattr(bar, prefix + key) for key in ("open", "high", "low", "close")]
            label = "還原" if prefix else ""
            invalid = [
                f"{label}{name}={value}"
                for name, value in zip(
                    ("開盤價", "最高價", "最低價", "收盤價"), prices, strict=True
                )
                if value is None or not math.isfinite(float(value)) or value <= 0
            ]
            if invalid:
                raise ValueError(f"{bar.trade_date} {'、'.join(invalid)}：價格必須為有效正數")
            opening, high, low, close = prices
            if not low <= min(opening, close) <= max(opening, close) <= high:
                raise ValueError(
                    f"{bar.trade_date} {label}價格高低關係錯誤："
                    f"開 {opening}、高 {high}、低 {low}、收 {close}"
                )
        if bar.volume is None or not math.isfinite(float(bar.volume)) or bar.volume < 0:
            raise ValueError(f"{bar.trade_date} 成交量無效：{bar.volume}")


def invalidate(db, item_id, rule_ids):
    for saved in db.scalars(
        select(WatchlistEvaluation).where(
            WatchlistEvaluation.item_id == item_id, WatchlistEvaluation.rule_id.in_(rule_ids)
        )
    ):
        saved.data_version = -1
    db.commit()


def process_stock(session_factory, item_id: int, ticker: str, rule_ids: list[int], day: date):
    with session_factory() as db:
        rules = list(
            db.scalars(
                select(WatchRule)
                .options(selectinload(WatchRule.conditions))
                .where(WatchRule.id.in_(rule_ids), WatchRule.is_enabled.is_(True))
            )
        )
        failures = []
        available = []
        days = 365 if not rules else 180
        for rule in rules:
            try:
                if not rule.conditions:
                    raise ValueError("戰法未設定條件")
                days = max(days, history_days(rule))
                available.append(rule)
            except Exception as exc:
                failures.append(f"{rule.name}：無法準備戰法（{exc}）")
                invalidate(db, item_id, [rule.id])
        try:
            if not db.get(HoldingsWatchlist, item_id):
                raise ValueError("觀察清單項目已移除")
            if MarketDataService(db).sync_daily_prices(ticker, days=days) == 0:
                raise ValueError("FinMind 未回傳行情")
            bars = MarketDataRepository(db).get_all_bars(ticker)
            validate_bars(bars, day)
            stock = db.scalar(select(Stock).where(Stock.ticker == ticker))
            if stock is None:
                raise ValueError("找不到股票主檔")
        except Exception as exc:
            db.rollback()
            invalidate(db, item_id, rule_ids)
            return failures + [f"行情更新／驗證失敗：{exc}"]
        kind = instrument_kind(db, ticker)
        version = stock.data_version
        for rule in available:
            try:
                result, state = evaluate_with_state(db, rule, ticker, kind=kind)
                # Only missing_friday_result() has no data date; real evaluations always do.
                missing_friday = (
                    rule.evaluation_frequency == "weekly" and result.data_date is None
                )
                if not missing_friday and (
                    result.status in ("error", "insufficient_data")
                    or any(not c.data_sufficient for c in result.condition_results)
                ):
                    raise ValueError("；".join(c.reason for c in result.condition_results))
                saved = db.scalar(
                    select(WatchlistEvaluation).where(
                        WatchlistEvaluation.item_id == item_id,
                        WatchlistEvaluation.rule_id == rule.id,
                    )
                )
                if saved is None:
                    saved = WatchlistEvaluation(item_id=item_id, rule_id=rule.id)
                    db.add(saved)
                saved.result = RuleEvaluationSchema(
                    **asdict(result), state=asdict(state),
                    protective_stop=protective_stop(result, kind)
                ).model_dump(mode="json", by_alias=True)
                saved.data_version = version
                saved.rule_fingerprint = fingerprint(rule)
                saved.evaluated_at = utcnow()
                db.commit()
            except Exception as exc:
                db.rollback()
                invalidate(db, item_id, [rule.id])
                failures.append(f"{rule.name}：{exc}")
        return failures
