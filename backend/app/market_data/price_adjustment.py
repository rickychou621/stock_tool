"""還原股價計算 — 依台灣證交所「除權除息參考價」公式反推調整係數。

公式：
    除權息參考價 = (除權息前收盤價 - 息值 + 現金增資認購價 * 現金增資配股率)
                   / (1 + 無償配股率 + 現金增資配股率)
    調整係數 = 除權息參考價 / 除權息前收盤價
    還原股價 = 該事件之前的歷史股價 * (事件當天之後所有調整係數的累乘)

註：股票股利(StockEarningsDistribution等)的單位是「元(以面額10元計)」，
換算成無償配股率要除以10 —— 例如股票股利3元代表無償配股率0.3。
本專案目前追蹤的股票近期都是純現金股利，這個換算沒有實際案例可以驗證單位，
先照公開慣例實作，之後如果遇到有股票股利的事件要留意核對。
"""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class PriceBar:
    trade_date: date
    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True)
class DividendEvent:
    ex_dividend_date: date
    cash_dividend: float = 0.0
    stock_dividend_ratio: float = 0.0
    cash_capital_increase_ratio: float = 0.0
    cash_capital_increase_price: float = 0.0


def calculate_adjustment_factor(prev_close: float, event: DividendEvent) -> float:
    denominator = 1 + event.stock_dividend_ratio + event.cash_capital_increase_ratio
    numerator = (
        prev_close
        - event.cash_dividend
        + event.cash_capital_increase_price * event.cash_capital_increase_ratio
    )
    ex_dividend_reference_price = numerator / denominator
    return ex_dividend_reference_price / prev_close


def _find_prev_close(sorted_bars: list[PriceBar], ex_dividend_date: date) -> float | None:
    prev_close = None
    for bar in sorted_bars:
        if bar.trade_date >= ex_dividend_date:
            break
        prev_close = bar.close
    return prev_close


def apply_adjustment(
    bars: list[PriceBar], events: list[DividendEvent]
) -> dict[date, dict[str, float]]:
    """回傳 {日期: {open, high, low, close}} 的還原股價結果。
    最新一段(還沒發生過除權息事件之前)維持跟原始股價一樣，
    往回每跨過一次事件的除權息日，之前的股價就再乘上該事件的調整係數。"""
    sorted_bars = sorted(bars, key=lambda b: b.trade_date)
    sorted_events = sorted(events, key=lambda e: e.ex_dividend_date)

    adjusted: dict[date, dict[str, float]] = {}
    cumulative_factor = 1.0
    event_idx = len(sorted_events) - 1

    for bar in reversed(sorted_bars):
        while event_idx >= 0 and sorted_events[event_idx].ex_dividend_date > bar.trade_date:
            event = sorted_events[event_idx]
            prev_close = _find_prev_close(sorted_bars, event.ex_dividend_date)
            if prev_close is not None and prev_close > 0:
                cumulative_factor *= calculate_adjustment_factor(prev_close, event)
            event_idx -= 1

        adjusted[bar.trade_date] = {
            "open": bar.open * cumulative_factor,
            "high": bar.high * cumulative_factor,
            "low": bar.low * cumulative_factor,
            "close": bar.close * cumulative_factor,
        }

    return adjusted
