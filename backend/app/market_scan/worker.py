import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import select

from app.conditions.types import ConditionBar
from app.market_data.models import Stock
from app.market_data.validation import is_no_trade, valid_ohlcv
from app.market_scan.data import prepare, required_days
from app.market_scan.models import DividendCoverage
from app.rules.evaluation import RuleEvaluationService


@dataclass
class Outcome:
    ticker: str
    candidates: list = field(default_factory=list)
    # status per selected rule: normal (including non-match), stale, insufficient_history.
    rules: dict = field(default_factory=dict)
    errors: list = field(default_factory=list)
    continuing: int = 0

    @property
    def succeeded(self):
        return any(v[0] == "normal" for v in self.rules.values())

    @property
    def failed(self):
        return any(v[0] == "stale" for v in self.rules.values())

    @property
    def insufficient(self):
        return any(v[0] == "insufficient_history" for v in self.rules.values())


def evaluate_stock(ticker, name, instrument_kind, rules, bars, dates):
    outcome = Outcome(ticker)
    valid_dates = set(dates)
    valid = [
        b for b in bars if b.trade_date in valid_dates and valid_ohlcv(b) and valid_ohlcv(b, True)
    ]
    if not valid:
        raise ValueError("沒有有效日K，請初始化歷史行情")
    latest = valid[-1]
    lag = sum(d > latest.trade_date for d in dates)
    if lag > 5:
        raise ValueError(f"行情落後 {lag} 個交易日，超過 5 日")
    # Bad historical rows cannot silently alter a rule's rolling sequence.
    invalid_history = [
        b
        for b in bars
        if b.trade_date < latest.trade_date
        and b.trade_date in valid_dates
        and not is_no_trade(b)
        and (not valid_ohlcv(b) or not valid_ohlcv(b, True))
    ]
    engine_bars = [
        ConditionBar(
            b.trade_date,
            float(b.adj_open),
            float(b.adj_high),
            float(b.adj_low),
            float(b.adj_close),
            b.volume,
        )
        for b in valid
    ]
    for rule in rules:
        try:
            cutoff = latest.trade_date - timedelta(days=required_days([rule]))
            invalid_for_rule = [b for b in invalid_history if b.trade_date >= cutoff]
            if invalid_for_rule:
                raise ValueError(f"{invalid_for_rule[-1].trade_date} 歷史行情無效，請重新初始化")
            result = RuleEvaluationService.evaluate_bars(rule, ticker, engine_bars)
            if result.status == "error":
                raise ValueError(
                    "戰法評估失敗：" + "；".join(c.reason for c in result.condition_results)
                )
            insufficient = any(not c.data_sufficient for c in result.condition_results)
            if insufficient:
                reason = "；".join(
                    c.reason for c in result.condition_results if not c.data_sufficient
                )
                outcome.rules[rule.id] = ("insufficient_history", reason)
                outcome.errors.append((rule.id, "insufficient_history", reason))
                continue
            outcome.rules[rule.id] = ("normal", None)
            if not result.is_met:
                continue
            previous = RuleEvaluationService.evaluate_bars(rule, ticker, engine_bars[:-1])
            if previous.status == "error":
                raise ValueError(
                    "前一個有效交易日戰法評估失敗："
                    + "；".join(c.reason for c in previous.condition_results)
                )
            if any(not c.data_sufficient for c in previous.condition_results):
                reason = "前一個有效交易日資料不足：" + "；".join(
                    c.reason for c in previous.condition_results if not c.data_sufficient
                )
                outcome.rules[rule.id] = ("insufficient_history", reason)
                outcome.errors.append((rule.id, "insufficient_history", reason))
                continue
            if previous.is_met:
                outcome.continuing += 1
                continue
            indicators = {
                f"{c.condition_id}.{k}": v
                for c in result.condition_results
                for k, v in c.indicators.items()
            }
            if any(not math.isfinite(v) for v in indicators.values()):
                raise ValueError("戰法指標含無效數字")
            reason = "；".join(c.reason for c in result.condition_results if c.is_met)
            outcome.candidates.append(
                dict(
                    ticker=ticker,
                    stock_name=name,
                    kind=instrument_kind,
                    rule_id=rule.id,
                    rule_name=rule.name,
                    status="normal",
                    status_reason=None,
                    reason=reason[:2000],
                    indicators=indicators,
                    close=float(latest.close),
                    price_date=latest.trade_date,
                    volume=latest.volume,
                    turnover=float(latest.turnover) if latest.turnover is not None else None,
                    scanned_at=datetime.utcnow(),
                    older_quote=lag > 0,
                )
            )
        except Exception as exc:
            reason = str(exc)[:1000]
            outcome.rules[rule.id] = ("stale", reason)
            outcome.errors.append((rule.id, "stale", reason))
    return outcome


def process_stock(factory, instrument, rules, kind, dates, limiter):
    ticker, instrument_kind, listed_on = instrument
    with factory() as db:
        bars = prepare(db, ticker, listed_on, kind, rules, dates, limiter)
        if kind == "initialize":
            if any(
                not is_no_trade(b) and (not valid_ohlcv(b) or not valid_ohlcv(b, True))
                for b in bars
            ):
                raise ValueError("歷史行情仍有無效資料，請查看來源警告並重新補缺")
            if not any(valid_ohlcv(b) and valid_ohlcv(b, True) for b in bars):
                raise ValueError("沒有有效日K，請先下載歷史行情")
            # Initialization reports data preparation, never strategy matches.
            return Outcome(ticker, rules={r.id: ("normal", None) for r in rules})
        coverage = db.get(DividendCoverage, ticker)
        start = max(listed_on, dates[-1] - timedelta(days=required_days(rules)))
        expected = next((d for d in dates if d >= start), start)
        if not coverage or coverage.start_date > expected or coverage.end_date < dates[-1]:
            reason = "還原資料未完整，請先執行補齊歷史股利；暫不評估戰法"
            return Outcome(
                ticker,
                rules={r.id: ("insufficient_history", reason) for r in rules},
                errors=[(r.id, "insufficient_history", reason) for r in rules],
            )
        stock = db.scalar(select(Stock).where(Stock.ticker == ticker))
        result = evaluate_stock(ticker, stock.name, instrument_kind, rules, bars, dates)
        if kind == "initialize":
            result.candidates = []
        return result
