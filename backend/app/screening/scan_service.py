"""手動掃描只產生結果與告警紀錄；Telegram 必須另外由使用者發送。"""

from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.alerts.models import AlertLog
from app.alerts.repository import AlertRepository
from app.core.config import get_settings
from app.market_data.repository import MarketDataRepository
from app.market_scan.models import MarketInstrument
from app.rules.repository import RuleRepository
from app.rules.state import ENTRY, EXIT, HOLD, NEAR_EXIT, evaluate_with_state, instrument_kind


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


class ScreeningScanService:
    def __init__(self, db: Session) -> None:
        self._rule_repository = RuleRepository(db)
        self._alert_repository = AlertRepository(db)
        self._market_data_repository = MarketDataRepository(db)
        self._db = db

    def run_scan(self) -> ScanSummary:
        rules = self._rule_repository.list_enabled()
        tickers = self._market_data_repository.list_chartable_tickers()
        categories = get_settings().excluded_etf_categories
        excluded_tickers = set(self._db.scalars(
            select(MarketInstrument.ticker).where(MarketInstrument.etf_category.in_(categories))
        )) if categories else set()
        scan_tickers = [ticker for ticker in tickers if ticker not in excluded_tickers]
        summary = ScanSummary(len(rules), len(scan_tickers), 0, len(tickers) - len(scan_tickers))
        tickers = scan_tickers
        names = self._market_data_repository.get_names(tickers)
        kinds: dict[str, str] = {}
        for rule in rules:
            for ticker in tickers:
                if ticker not in kinds:
                    kinds[ticker] = instrument_kind(self._db, ticker)
                try:
                    result, state = evaluate_with_state(
                        self._db, rule, ticker,
                        kind=kinds[ticker],
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
        return summary
