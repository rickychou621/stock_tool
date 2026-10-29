"""手動掃描只產生結果與告警紀錄；Telegram 必須另外由使用者發送。"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.alerts.models import AlertLog
from app.alerts.repository import AlertRepository
from app.market_data.models import StockPriceDaily
from app.market_data.repository import MarketDataRepository
from app.market_scan.models import MarketInstrument
from app.market_scan.service import excluded_etf_categories
from app.rules.frequency import last_evaluation_day
from app.rules.repository import RuleRepository
from app.rules.state import (
    ENTRY,
    EXIT,
    HOLD,
    NEAR_EXIT,
    STALE,
    evaluate_with_state,
    instrument_kind,
)


@dataclass
class ScanMatch:
    id: int | None
    ticker: str
    name: str
    reason: str
    rule_name: str
    price_at_trigger: float | None
    data_date: date | None
    is_notified: bool
    reasons: list[str]
    state: str


@dataclass
class ScanIssue:
    ticker: str
    rule_name: str
    reason: str


@dataclass
class ScanSummary:
    rules_evaluated: int
    stocks_scanned: int
    new_alerts: int
    excluded: int
    matches: list[ScanMatch] = field(default_factory=list)
    issues: list[ScanIssue] = field(default_factory=list)
    excluded_categories: list[str] = field(default_factory=list)


class ScreeningScanService:
    def __init__(self, db: Session) -> None:
        self._rule_repository = RuleRepository(db)
        self._alert_repository = AlertRepository(db)
        self._market_data_repository = MarketDataRepository(db)
        self._db = db

    def run_scan(self, progress: Callable[[int, int], None] | None = None) -> ScanSummary:
        rules = self._rule_repository.list_enabled()
        tickers = self._market_data_repository.list_chartable_tickers()
        latest_date = self._db.scalar(select(func.max(StockPriceDaily.trade_date)))
        trading_days = list(self._db.scalars(
            select(StockPriceDaily.trade_date).distinct()
            .where(StockPriceDaily.trade_date >= latest_date - timedelta(days=21))
        )) if latest_date else []
        categories = excluded_etf_categories(self._db)
        excluded_tickers = set(self._db.scalars(
            select(MarketInstrument.ticker).where(MarketInstrument.etf_category.in_(categories))
        )) if categories else set()
        scan_tickers = [ticker for ticker in tickers if ticker not in excluded_tickers]
        summary = ScanSummary(len(rules), len(scan_tickers), 0, len(tickers) - len(scan_tickers))
        summary.excluded_categories = sorted(categories)
        tickers = scan_tickers
        names = self._market_data_repository.get_names(tickers)
        if progress:
            progress(0, len(tickers))
        for done, ticker in enumerate(tickers, start=1):
            kind = instrument_kind(self._db, ticker) if rules else None
            for rule in rules:
                try:
                    result, state = evaluate_with_state(
                        self._db, rule, ticker,
                        kind=kind,
                    )
                except (ValueError, TypeError, ArithmeticError):
                    summary.issues.append(
                        ScanIssue(ticker, rule.name, "評估失敗，請檢查規則參數。")
                    )
                    continue
                if result.status in ("insufficient_data", "error"):
                    summary.issues.append(
                        ScanIssue(
                            ticker, rule.name, "；".join(c.reason for c in result.condition_results)
                        )
                    )
                if state.state not in (ENTRY, HOLD, NEAR_EXIT, EXIT):
                    continue
                # Weekly rules are judged on the last Friday, not on the latest trading day.
                expected = latest_date and last_evaluation_day(
                    latest_date, trading_days, rule.evaluation_frequency
                )
                if result.data_date is not None and expected and result.data_date < expected:
                    state.state = STALE
                    state.reason = (
                        f"行情過期：最後行情 {result.data_date}，最近交易日 {expected}"
                    )
                latest_bar = self._market_data_repository.get_latest_bar(ticker)
                price = None
                if latest_bar:
                    price = float(
                        latest_bar.adj_close
                        if latest_bar.adj_close is not None
                        else latest_bar.close
                    )
                reasons = [c.reason for c in result.condition_results]
                message = (
                    f"{ticker} 符合「{rule.name}」\n"
                    f"行情日期：{result.data_date}，參考價：{price}\n" + "\n".join(reasons)
                )
                alert = None
                if state.state == ENTRY:
                    alert = self._alert_repository.get_today(rule.id, ticker)
                    if alert is None:
                        alert = self._alert_repository.create(
                            AlertLog(
                                rule_id=rule.id,
                                ticker=ticker,
                                price_at_trigger=price,
                                message=message,
                                is_notified=False,
                                state=state.state,
                            )
                        )
                        summary.new_alerts += 1
                    elif not alert.is_notified:
                        alert.state = state.state
                        self._alert_repository.update_message(alert, message)
                # Return this scan's matches even when today's alert already exists.
                summary.matches.append(
                    ScanMatch(
                        id=alert.id if alert else None,
                        state=state.state,
                        ticker=ticker,
                        name=names.get(ticker, ""),
                        reason=state.reason,
                        rule_name=rule.name,
                        price_at_trigger=price,
                        data_date=result.data_date,
                        is_notified=alert.is_notified if alert else False,
                        reasons=[c.reason for c in result.condition_results],
                    )
                )
            if progress:
                progress(done, len(tickers))
        return summary
