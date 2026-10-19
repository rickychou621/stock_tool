"""TWSE HTTP entry point: one process-wide paced budget, no automatic retries."""

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from functools import lru_cache

import httpx

from app.core.config import get_settings
from app.market_data.validation import valid_ohlcv
from app.market_scan.rate_limit import RateLimiter

BASE = "https://www.twse.com.tw/exchangeReport/"


@lru_cache
def shared_limiter():
    return RateLimiter(60 / get_settings().twse_min_request_interval_seconds)


def get(url, *, client=None, **kwargs):
    shared_limiter().acquire()
    response = (client or httpx).get(url, **kwargs)
    response.raise_for_status()
    return response


def number(value):
    return Decimal(str(value).strip().replace(",", ""))


def parse_daily(payload, day, active):
    if payload.get("stat") != "OK" or payload.get("date") != day.strftime("%Y%m%d"):
        raise ValueError("證交所當日行情尚未取得：日期不符或來源尚未發布")
    tables = [
        t for t in payload.get("tables", []) if {"證券代號", "開盤價"} <= set(t.get("fields", []))
    ]
    if len(tables) != 1:
        raise ValueError("證交所行情欄位不完整")
    table = tables[0]
    fields = table["fields"]
    mapping = {
        "open": "開盤價",
        "high": "最高價",
        "low": "最低價",
        "close": "收盤價",
        "volume": "成交股數",
        "turnover": "成交金額",
    }
    if not set(mapping.values()) <= set(fields) or not table.get("data"):
        raise ValueError("證交所行情表缺少欄位或資料")
    rows, invalid, seen = [], {}, set()
    for cells in table["data"]:
        row = dict(zip(fields, cells, strict=False))
        ticker = str(row.get("證券代號", "")).strip()
        if ticker not in active:
            continue
        if ticker in seen:
            raise ValueError("證交所行情代號重複")
        seen.add(ticker)
        if len(cells) != len(fields):
            invalid[ticker] = "行情列欄位數量不符"
            continue
        if any(str(row[f]).strip() in ("", "--") for f in list(mapping.values())[:4]):
            continue
        try:
            bar = {k: number(row[v]) for k, v in mapping.items()}
            if (
                not valid_ohlcv(bar)
                or not bar["turnover"].is_finite()
                or bar["turnover"] < 0
                or bar["volume"] != bar["volume"].to_integral_value()
            ):
                raise ValueError("OHLCV 或成交金額無效")
            bar["volume"] = int(bar["volume"])
            rows.append(dict(ticker=ticker, trade_date=day, **bar))
        except (InvalidOperation, ValueError, OverflowError, TypeError):
            invalid[ticker] = "證交所 OHLCV 或成交金額無效，未寫入"
    absent = set(active) - {r["ticker"] for r in rows} - set(invalid)
    return rows, absent, invalid


def parse_events(payload, start, end):
    if payload.get("stat") == "很抱歉，沒有符合條件的資料!":
        return []
    if payload.get("stat") != "OK":
        raise ValueError("證交所除權息事件尚未取得")
    fields = payload.get("fields", [])
    if not {"資料日期", "股票代號"} <= set(fields):
        raise ValueError("證交所除權息欄位不完整")
    events = set()
    for cells in payload.get("data", []):
        row = dict(zip(fields, cells, strict=True))
        parts = re.findall(r"\d+", row["資料日期"])
        if len(parts) != 3:
            raise ValueError("證交所除權息日期格式異常")
        y, m, d = map(int, parts)
        day = date(y + 1911 if y < 1911 else y, m, d)
        if not start <= day <= end:
            raise ValueError("證交所除權息日期超出查詢範圍")
        events.add((str(row["股票代號"]).strip(), day))
    return sorted(events)


class TwseBatchClient:
    def daily(self, day, active):
        response = get(
            BASE + "MI_INDEX",
            params={"response": "json", "date": day.strftime("%Y%m%d"), "type": "ALLBUT0999"},
            timeout=40,
        )
        return parse_daily(response.json(), day, active)

    def events(self, start, end):
        response = get(
            BASE + "TWT49U",
            params={
                "response": "json",
                "startDate": start.strftime("%Y%m%d"),
                "endDate": end.strftime("%Y%m%d"),
            },
            timeout=40,
        )
        return parse_events(response.json(), start, end)

    def price_events(self, start, end):
        response = get(
            BASE + "TWTAUU",
            params={
                "response": "json",
                "startDate": start.strftime("%Y%m%d"),
                "endDate": end.strftime("%Y%m%d"),
            },
            timeout=40,
        )
        return parse_price_events(response.json(), start, end)

    def tpex_price_events(self, start, end):
        response = get(
            "https://www.tpex.org.tw/www/zh-tw/bulletin/revivt",
            params={
                "response": "json",
                "startDate": start.strftime("%Y/%m/%d"),
                "endDate": end.strftime("%Y/%m/%d"),
            },
            timeout=40,
        )
        return parse_tpex_price_events(response.json(), start, end)


def parse_price_events(payload, start, end):
    from app.data_source.price_events import price_event

    if payload.get("stat") == "很抱歉，沒有符合條件的資料!":
        return []
    if payload.get("stat") != "OK":
        raise ValueError("證交所減資事件尚未取得")
    fields = payload.get("fields", [])
    if not {"恢復買賣日期", "股票代號", "停止買賣前收盤價格", "恢復買賣參考價"} <= set(fields):
        raise ValueError("證交所減資欄位不完整")
    events = []
    for cells in payload.get("data", []):
        row = dict(zip(fields, cells, strict=True))
        parts = re.findall(r"\d+", row["恢復買賣日期"])
        if len(parts) != 3:
            raise ValueError("證交所減資日期格式異常")
        y, m, d = map(int, parts)
        events.append(
            price_event(
                str(row["股票代號"]).strip(),
                date(y + 1911 if y < 1911 else y, m, d),
                "capital_reduction",
                row["停止買賣前收盤價格"],
                row["恢復買賣參考價"],
                "twse_twtauu",
                start,
                end,
            )
        )
    return events


def parse_tpex_price_events(payload, start, end):
    from app.data_source.price_events import price_event

    if payload.get("stat") != "ok":
        raise ValueError("櫃買減資事件尚未取得")
    required = {"恢復買賣日期", "股票代號", "最後交易日之收盤價格", "減資恢復買賣開始日參考價格"}
    tables = [t for t in payload.get("tables", []) if required <= set(t.get("fields", []))]
    if len(tables) != 1:
        raise ValueError("櫃買減資欄位不完整")
    table = tables[0]
    events = []
    for cells in table["data"]:
        row = dict(zip(table["fields"], cells, strict=True))
        value = str(row["恢復買賣日期"]).strip()
        if not re.fullmatch(r"\d{7}", value):
            raise ValueError("櫃買減資日期格式異常")
        day = date(int(value[:3]) + 1911, int(value[3:5]), int(value[5:]))
        events.append(
            price_event(
                str(row["股票代號"]).strip(),
                day,
                "capital_reduction",
                row["最後交易日之收盤價格"],
                row["減資恢復買賣開始日參考價格"],
                "tpex_revivt",
                start,
                end,
            )
        )
    return events
