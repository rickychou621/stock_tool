"""Official TWSE ISIN classification; reject incomplete downloads before deactivation."""

from collections import Counter
from datetime import date
from html.parser import HTMLParser

from sqlalchemy import select

from app.data_source import twse_client
from app.market_data.models import Stock
from app.market_scan.models import MarketInstrument

URL = "https://isin.twse.com.tw/isin/C_public.jsp?strMode=2"


class TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows, self.row, self.cell = [], [], None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.row = []
        if tag in ("td", "th"):
            self.cell = ""

    def handle_data(self, data):
        if self.cell is not None:
            self.cell += data

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.cell is not None:
            self.row.append(self.cell.strip())
            self.cell = None
        if tag == "tr":
            self.rows.append(self.row)


def parse_universe(html, today):
    parser = TableParser()
    parser.feed(html)
    section, seen, rows, sections = "", set(), [], set()
    for cells in parser.rows:
        if len(cells) == 1:
            section = cells[0]
            sections.add(section)
            continue
        if len(cells) != 7 or not cells[3].startswith("上市"):
            continue
        kind = None
        if section in ("股票", "創新板") and cells[5].startswith("ES"):
            kind = "stock"
        if section == "ETF" and cells[5].startswith("CE"):
            kind = "etf"
        if kind is None:
            continue
        ticker, name = cells[0].split(maxsplit=1)
        listed = date.fromisoformat(cells[2].replace("/", "-"))
        if listed > today:
            continue
        if ticker in seen:
            raise ValueError("證交所名單代碼重複")
        seen.add(ticker)
        rows.append(dict(ticker=ticker, name=name, kind=kind, listed_on=listed, sector=cells[4]))
    if not {"股票", "ETF", "ETN"} <= sections:
        raise ValueError("證交所名單缺少完整分類，沿用舊名單")
    return rows


def fetch_universe(today):
    response = twse_client.get(URL, timeout=40)
    response.raise_for_status()
    return parse_universe(response.content.decode("cp950"), today)


def refresh_universe(db, today, fetch=fetch_universe):
    try:
        rows = fetch(today)
        counts = Counter(r["kind"] for r in rows)
        existing = list(
            db.scalars(select(MarketInstrument).where(MarketInstrument.active.is_(True)))
        )
        previous = Counter(r.kind for r in existing)
        # Reject structural truncation and >10% sudden loss in either category.
        if (
            counts["stock"] < 800
            or counts["etf"] < 100
            or any(counts[k] < n * 0.9 for k, n in previous.items())
        ):
            raise ValueError("證交所名單完整性檢查未通過")
        stocks = {s.ticker: s for s in db.scalars(select(Stock))}
        instruments = {s.ticker: s for s in db.scalars(select(MarketInstrument))}
        current = set()
        for row in rows:
            ticker = row["ticker"]
            current.add(ticker)
            stock = stocks.get(ticker)
            if stock is None:
                stock = Stock(ticker=ticker, name=row["name"], market="上市", sector=row["sector"])
                db.add(stock)
            else:
                stock.name = row["name"]
        # Explicit parent flush: SQLAlchemy has no relationship between these mappers.
        db.flush()
        for row in rows:
            ticker = row["ticker"]
            item = instruments.get(ticker)
            if item is None:
                item = MarketInstrument(ticker=ticker)
                db.add(item)
            item.market, item.kind, item.listed_on, item.active = (
                "TWSE",
                row["kind"],
                row["listed_on"],
                True,
            )
        for item in instruments.values():
            if item.market == "TWSE" and item.ticker not in current:
                item.active = False
        db.commit()
        warning = None
    except Exception as exc:
        db.rollback()
        warning = f"上市名單更新失敗，沿用最近有效名單：{type(exc).__name__}: {str(exc)[:200]}"
    universe = list(
        db.scalars(
            select(MarketInstrument)
            .where(MarketInstrument.active.is_(True), MarketInstrument.market == "TWSE")
            .order_by(MarketInstrument.ticker)
        )
    )
    if not universe:
        raise ValueError("沒有可用上市名單；" + (warning or "名單為空"))
    return [(i.ticker, i.kind, i.listed_on) for i in universe], warning
