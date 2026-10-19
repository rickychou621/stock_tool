"""Use TWSE's actual monthly trading dates, including unscheduled market closures."""

from datetime import date

from app.data_source import twse_client


class TwseCalendar:
    def is_trading_day(self, day: date) -> bool:
        if day.weekday() >= 5:
            return False
        response = twse_client.get(
            "https://www.twse.com.tw/exchangeReport/FMTQIK",
            params={"response": "json", "date": day.replace(day=1).strftime("%Y%m%d")},
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        # The exchange has not published any trades this month (e.g. New Year).
        if payload.get("stat") == "很抱歉，沒有符合條件的資料!":
            return False
        if payload.get("stat") != "OK" or not isinstance(payload.get("data"), list):
            raise ValueError("證交所交易日期資料異常，未執行行情更新")
        days = set()
        for row in payload["data"]:
            year, month, day_number = map(int, row[0].split("/"))
            parsed = date(year + 1911, month, day_number)
            if (parsed.year, parsed.month) != (day.year, day.month):
                raise ValueError("證交所回傳的交易月份不符")
            days.add(parsed)
        return day in days
