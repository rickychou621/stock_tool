"""FinMind API 封裝(日K股價)。

FinMind的 TaiwanStockPriceAdj(還原股價)實測目前需要付費會員才能查詢
(免費/匿名請求會被拒絕:「Your level is free. Please update your user level.」)，
所以這裡改用 TaiwanStockPrice(未還原除權息的原始股價)，免費且不需要申請token。
還原股價之後若要補上，可以走「自己拿股利資料回推」的方案，或申請FinMind付費方案。
"""

from datetime import date, timedelta

import httpx

FINMIND_BASE_URL = "https://api.finmindtrade.com/api/v4/data"


def _fetch(dataset: str, ticker: str, start_date: date | None = None) -> list[dict]:
    params: dict[str, str] = {"dataset": dataset, "data_id": ticker}
    if start_date:
        params["start_date"] = start_date.isoformat()

    response = httpx.get(FINMIND_BASE_URL, params=params, timeout=15)
    # FinMind的錯誤(例如免費額度限制)一樣會回傳可解析的JSON、只是status不是200，
    # 不能只靠HTTP status code判斷，所以這裡不呼叫raise_for_status()。
    payload = response.json()

    if payload.get("status") != 200:
        raise RuntimeError(f"FinMind回應錯誤：{payload.get('msg')}")

    return payload["data"]


class FinMindClient:
    def get_daily_price(self, ticker: str, days: int = 180) -> list[dict]:
        start_date = date.today() - timedelta(days=days)
        rows = _fetch("TaiwanStockPrice", ticker, start_date)

        return [
            {
                "trade_date": date.fromisoformat(row["date"]),
                "open": row["open"],
                "high": row["max"],
                "low": row["min"],
                "close": row["close"],
                "volume": int(row["Trading_Volume"]),
            }
            for row in rows
        ]

    def get_dividend_events(self, ticker: str, days: int = 730) -> list[dict]:
        """抓股利/增資事件，用來反推還原股價(見 market_data/price_adjustment.py)。
        預設抓過去2年，涵蓋大部分股票一年一次或一年多次的配息週期。"""
        start_date = date.today() - timedelta(days=days)
        rows = _fetch("TaiwanStockDividend", ticker, start_date)

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
