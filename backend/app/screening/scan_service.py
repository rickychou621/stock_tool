"""手動掃描只產生結果與告警紀錄；Telegram 必須另外由使用者發送。"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.alerts.models import AlertLog
from app.alerts.repository import AlertRepository
from app.market_data.repository import MarketDataRepository
from app.market_scan.models import MarketInstrument
from app.market_scan.service import excluded_etf_categories
from app.rules.freshness import expected_data_date, latest_trading_days
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
    rule_id: int
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
    evaluation_frequency: str = "daily"


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
    baseline_date: date | None = None
    finished_at: datetime | None = None


class ScreeningScanService:
    def __init__(self, db: Session) -> None:
        self._rule_repository = RuleRepository(db)
        self._alert_repository = AlertRepository(db)
        self._market_data_repository = MarketDataRepository(db)
        self._db = db

    def run_scan(self, progress: Callable[[int, int], None] | None = None) -> ScanSummary:
        rules = self._rule_repository.list_enabled()
        tickers = self._market_data_repository.list_chartable_tickers()
        latest_date, trading_days = latest_trading_days(self._db)
        categories = excluded_etf_categories(self._db)
        excluded_tickers = set(self._db.scalars(
            select(MarketInstrument.ticker).where(MarketInstrument.etf_category.in_(categories))
        )) if categories else set()
        scan_tickers = [ticker for ticker in tickers if ticker not in excluded_tickers]
        summary = ScanSummary(len(rules), len(scan_tickers), 0, len(tickers) - len(scan_tickers))
        summary.baseline_date = latest_date
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
                            ticker, rule.name,
                            "；".join(dict.fromkeys(c.reason for c in result.condition_results))
                        )
                    )
                if state.state not in (ENTRY, HOLD, NEAR_EXIT, EXIT):
                    continue
                # Weekly rules are judged on the last Friday, not on the latest trading day.
                expected = expected_data_date(
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
                        rule_id=rule.id,
                        id=alert.id if alert else None,
                        state=state.state,
                        ticker=ticker,
                        name=names.get(ticker, ""),
                        reason=state.reason,
                        rule_name=rule.name,
                        evaluation_frequency=rule.evaluation_frequency,
                        price_at_trigger=price,
                        data_date=result.data_date,
                        is_notified=alert.is_notified if alert else False,
                        reasons=[c.reason for c in result.condition_results],
                    )
                )
            if progress:
                progress(done, len(tickers))
        summary.finished_at = datetime.now(UTC)
        return summary
