"""FinMind 原始股價與股利；token 以 Authorization header 傳送。"""

from datetime import date, timedelta

import httpx

from app.core.config import get_settings

FINMIND_BASE_URL = "https://api.finmindtrade.com/api/v4/data"


def _fetch(
    dataset: str, ticker: str, start_date: date | None = None, end_date: date | None = None
) -> list[dict]:
    params: dict[str, str] = {"dataset": dataset}
    if ticker:
        params["data_id"] = ticker
    if start_date:
        params["start_date"] = start_date.isoformat()

    if end_date:
        params["end_date"] = end_date.isoformat()

    token = get_settings().finmind_api_token.strip()
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        response = httpx.get(FINMIND_BASE_URL, params=params, headers=headers, timeout=15)
        payload = response.json()
    except Exception:
        raise RuntimeError("FinMind回應錯誤：連線或資料格式異常") from None
    if (
        response.is_error
        or not isinstance(payload, dict)
        or payload.get("status") != 200
        or not isinstance(payload.get("data"), list)
    ):
        # Source messages may echo credentials. Never expose arbitrary response text.
        raise RuntimeError("FinMind回應錯誤：來源拒絕請求，請確認權限或額度")

    return payload["data"]


class FinMindClient:
    def __init__(self, before_request=None):
        self.before_request = before_request or (lambda: None)

    def get_daily_price(
        self, ticker: str, days: int = 180, *, start_date=None, end_date=None
    ) -> list[dict]:
        start_date = start_date or date.today() - timedelta(days=days)
        self.before_request()
        rows = _fetch("TaiwanStockPrice", ticker, start_date, end_date)

        return [
            {
                "trade_date": date.fromisoformat(row["date"]),
                "open": row["open"],
                "high": row["max"],
                "low": row["min"],
                "close": row["close"],
                "volume": int(row["Trading_Volume"]),
                "turnover": row.get("Trading_money"),
            }
            for row in rows
        ]

    def get_dividend_events(
        self, ticker: str, days: int = 730, *, start_date=None, end_date=None
    ) -> list[dict]:
        """抓股利/增資事件，用來反推還原股價(見 market_data/price_adjustment.py)。
        預設抓過去2年，涵蓋大部分股票一年一次或一年多次的配息週期。"""
        start_date = start_date or date.today() - timedelta(days=days)
        self.before_request()
        rows = _fetch("TaiwanStockDividend", ticker, start_date, end_date)

        events = []
        for row in rows:
            ex_date_str = row.get("CashExDividendTradingDate") or row.get(
                "StockExDividendTradingDate"
            )
            if not ex_date_str:
                continue  # 還沒公告確切除權息日，先跳過

            cash_dividend = (row.get("CashEarningsDistribution") or 0) + (
                row.get("CashStatutorySurplus") or 0
            )
            # 股票股利以面額10元計算，換算成無償配股率要除以10。
            stock_dividend_ratio = (
                (row.get("StockEarningsDistribution") or 0)
                + (row.get("StockStatutorySurplus") or 0)
            ) / 10
            cash_increase_ratio = row.get("CashIncreaseSubscriptionRate") or 0
            cash_increase_price = row.get("CashIncreaseSubscriptionpRrice") or 0

            if cash_dividend == 0 and stock_dividend_ratio == 0 and cash_increase_ratio == 0:
                continue  # 這筆事件沒有實質配發，跳過

            events.append(
                {
                    "ex_dividend_date": date.fromisoformat(ex_date_str),
                    "cash_dividend": cash_dividend,
                    "stock_dividend_ratio": stock_dividend_ratio,
                    "cash_capital_increase_ratio": cash_increase_ratio,
                    "cash_capital_increase_price": cash_increase_price,
                }
            )
        return events

    def get_price_events(self, *, start_date, end_date):
        from app.data_source.price_events import parse_finmind

        self.before_request()
        return parse_finmind(
            _fetch("TaiwanStockSplitPrice", "", start_date, end_date), start_date, end_date
        )
