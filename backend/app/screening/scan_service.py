"""手動掃描只產生結果與告警紀錄；Telegram 必須另外由使用者發送。"""

from dataclasses import dataclass, field
from datetime import date

from sqlalchemy.orm import Session

from app.alerts.models import AlertLog
from app.alerts.repository import AlertRepository
from app.market_data.repository import MarketDataRepository
from app.rules.evaluation import RuleEvaluationService
from app.rules.repository import RuleRepository


@dataclass
class ScanMatch:
    id: int
    ticker: str
    rule_name: str
    price_at_trigger: float | None
    data_date: date | None
    is_notified: bool
    reasons: list[str]


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
    matches: list[ScanMatch] = field(default_factory=list)
    issues: list[ScanIssue] = field(default_factory=list)


class ScreeningScanService:
    def __init__(self, db: Session) -> None:
        self._rule_repository = RuleRepository(db)
        self._alert_repository = AlertRepository(db)
        self._market_data_repository = MarketDataRepository(db)
        self._evaluation_service = RuleEvaluationService(db)

    def run_scan(self) -> ScanSummary:
        rules = self._rule_repository.list_enabled()
        tickers = self._market_data_repository.list_chartable_tickers()
        summary = ScanSummary(len(rules), len(tickers), 0)
        for rule in rules:
            for ticker in tickers:
                try:
                    result = self._evaluation_service.evaluate(rule, ticker)
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
                if not result.is_met:
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
                alert = self._alert_repository.get_today(rule.id, ticker)
                if alert is None:
                    alert = self._alert_repository.create(
                        AlertLog(
                            rule_id=rule.id,
                            ticker=ticker,
                            price_at_trigger=price,
                            message=message,
                            is_notified=False,
                        )
                    )
                    summary.new_alerts += 1
                elif not alert.is_notified:
                    self._alert_repository.update_message(alert, message)
                # Return this scan's matches even when today's alert already exists.
                summary.matches.append(
                    ScanMatch(
                        id=alert.id,
                        ticker=ticker,
                        rule_name=rule.name,
                        price_at_trigger=price,
                        data_date=result.data_date,
                        is_notified=alert.is_notified,
                        reasons=[c.reason for c in result.condition_results],
                    )
                )
        return summary
