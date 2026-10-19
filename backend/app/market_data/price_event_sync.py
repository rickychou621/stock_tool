"""Serialize all-market corporate actions across jobs and backend processes."""

from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime
from threading import Lock
from zoneinfo import ZoneInfo

from sqlalchemy import select, text

from app.data_source.finmind_client import FinMindClient
from app.data_source.twse_client import TwseBatchClient
from app.market_data.models import Stock, StockPriceEventSync
from app.market_data.service import MarketDataService

_local_lock = Lock()
START = date(2011, 1, 1)


@dataclass
class SyncResult:
    complete: bool = False
    warnings: list[str] = field(default_factory=list)
    twse_requests: int = 0
    tpex_requests: int = 0


@contextmanager
def sync_lock(factory):
    with _local_lock:
        with factory() as db:
            bind = db.get_bind()
        if bind.dialect.name != "mysql":
            yield
            return
        with bind.connect() as connection:
            acquired = connection.scalar(text("SELECT GET_LOCK('stock_tool_price_events', 180)"))
            if acquired != 1:
                raise RuntimeError("價格事件同步鎖逾時")
            try:
                yield
            finally:
                connection.execute(text("SELECT RELEASE_LOCK('stock_tool_price_events')"))


def sync_market_price_events(db_factory, start, end, *, before_finmind=None, client=None):
    """Requested windows share one fixed 2011..today fetch; failures retry next invocation.

    Only successful storage of all three sources marks the day complete. No source
    is retried within an invocation. Return sanitized warnings to the job owner.
    """
    result = SyncResult()
    try:
        with sync_lock(db_factory):
            today = datetime.now(ZoneInfo("Asia/Taipei")).date()
            with db_factory() as db:
                # Reserve the shared benchmark before any job can mark today complete.
                if db.scalar(select(Stock).where(Stock.ticker == "0050")) is None:
                    db.add(Stock(ticker="0050", name="元大台灣50", market="上市"))
                    db.commit()
                record = db.get(StockPriceEventSync, 1)
                if record and record.synced_on == today and record.complete:
                    result.complete = True
                    return result
                db.merge(StockPriceEventSync(id=1, synced_on=today, complete=False))
                db.commit()
            client = client or TwseBatchClient()
            sources = [
                (
                    "FinMind split",
                    lambda: FinMindClient(before_request=before_finmind).get_price_events(
                        start_date=START, end_date=today
                    ),
                ),
            ]
            # Full 2011..2026 range verified against both exchanges.
            sources.append(("TWTAUU", lambda: client.price_events(START, today)))
            sources.append(("TPEx revivt", lambda: client.tpex_price_events(START, today)))
            rows = []
            for source, fetch in sources:
                try:
                    result.twse_requests += source == "TWTAUU"
                    result.tpex_requests += source == "TPEx revivt"
                    rows.extend(fetch())
                except Exception:
                    result.warnings.append(f"{source} 價格事件來源失敗，本次未重試；下次呼叫可重試")
            if result.warnings:
                return result
            with db_factory() as db:
                known = set(db.scalars(select(Stock.ticker)))
                grouped = defaultdict(list)
                for row in rows:
                    if row["ticker"] in known:
                        grouped[row["ticker"]].append(row)
                for ticker, events in sorted(grouped.items()):
                    MarketDataService(db).import_price_events(ticker, events)
                db.get(StockPriceEventSync, 1).complete = True
                db.commit()
            result.complete = True
    except Exception:
        result.warnings.append("價格事件同步或寫入失敗，本次未重試；下次呼叫可重試")
    return result
