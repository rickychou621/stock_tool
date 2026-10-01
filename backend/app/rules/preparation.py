"""使用者按下評估後，先準備該規則需要的行情；不執行規則判斷。"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.conditions.registry import get_condition
from app.market_data.models import Stock
from app.market_data.service import MarketDataService
from app.rules.models import WatchRule


class PreparationError(ValueError):
    pass


def history_days(rule: WatchRule) -> int:
    days = 180
    for item in rule.conditions:
        condition = get_condition(item.condition_id)
        params = item.params or {}
        periods = [
            int(params.get(key, default))
            for key, default in (
                ("period", 20),
                ("long_period", 26),
                ("lookback", 20),
                ("slope_lookback", 5),
                ("short_period", 12),
                ("signal_period", 9),
            )
        ]
        if any(value <= 0 for value in periods):
            raise PreparationError("規則週期必須大於零，請先修正规則參數。")
        # Calendar-day budget includes weekends and a partial current month.
        required = (
            (max(periods) + 3) * 31 if condition.required_timeframe == "月K" else sum(periods) * 3
        )
        days = max(days, required)
    return min(days, 1000)


class EvaluationPreparationService:
    def __init__(self, db: Session) -> None:
        self._db = db
        self._market = MarketDataService(db)

    def prepare(self, rule: WatchRule, ticker: str) -> int:
        stock = self._db.scalar(select(Stock).where(Stock.ticker == ticker))
        if stock is None:
            raise PreparationError("股票尚未建立主檔，請先選擇系統已有的股票。")
        rows = self._market.sync_daily_prices(ticker, days=history_days(rule))
        if rows == 0:
            raise PreparationError("資料來源未回傳行情，本次未評估；請確認代號後重試。")
        return rows
