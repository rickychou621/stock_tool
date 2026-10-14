"""Exercise native MySQL SQL using connection-local temporary tables only."""

from datetime import date, datetime
from unittest.mock import Mock

from sqlalchemy import select
from sqlalchemy.exc import StatementError
from sqlalchemy.orm import Session

from app.core.db import engine
from app.market_data.models import Stock, StockPriceDaily
from app.market_data.service import MarketDataService
from app.market_scan.models import ScanCandidate, ScanPublication, ScanTask
from app.market_scan.publication import publish
from app.market_scan.worker import Outcome

with engine.connect() as connection:
    for table in (
        "stocks",
        "stock_price_daily",
        "stock_dividend_events",
        "market_scan_candidates",
        "market_scan_indicators",
        "market_scan_tasks",
        "market_scan_publication",
    ):
        ddl = connection.exec_driver_sql(f"SHOW CREATE TABLE {table}").one()[1]
        ddl = "\n".join(line for line in ddl.splitlines() if "FOREIGN KEY" not in line)
        ddl = ddl.replace("CREATE TABLE", "CREATE TEMPORARY TABLE", 1).replace(",\n)", "\n)")
        connection.exec_driver_sql(ddl)
    connection.commit()
    with Session(bind=connection) as db:
        db.add(Stock(ticker="TEST", name="暫存測試", market="上市"))
        db.commit()
        day = date(2026, 10, 12)
        client = Mock()
        client.get_daily_price.return_value = [
            dict(trade_date=day, open=10, high=12, low=9, close=11, volume=0, turnover=1234)
        ]
        client.get_dividend_events.return_value = []
        market = MarketDataService(db, client)
        assert market.sync_daily_prices("TEST", start_date=day, end_date=day) == 1
        bar = db.scalar(select(StockPriceDaily))
        assert float(bar.adj_close) == 11 and float(bar.turnover) == 1234
        client.get_daily_price.return_value[0]["turnover"] = None
        market.sync_daily_prices("TEST", start_date=day, end_date=day)
        db.refresh(bar)
        assert float(bar.turnover) == 1234
        client.get_daily_price.return_value[0]["open"] = 0
        try:
            market.sync_daily_prices("TEST", start_date=day, end_date=day)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid data accepted")
        db.refresh(bar)
        assert float(bar.open) == 10
        db.add(
            ScanTask(
                kind="scan",
                batch_id="a",
                source="manual",
                status="running",
                started_at=datetime.utcnow(),
                rules=[{"id": 1, "name": "test"}],
                warnings=[],
            )
        )
        db.commit()
        values = dict(
            ticker="TEST",
            stock_name="暫存測試",
            kind="stock",
            rule_id=1,
            rule_name="test",
            status="normal",
            reason="命中",
            indicators={"test.value": 10},
            close=11,
            price_date=day,
            volume=0,
            turnover=None,
            scanned_at=datetime.utcnow(),
            older_quote=False,
        )
        outcome = Outcome("TEST", candidates=[values], rules={1: ("normal", None)})
        metadata = dict(
            batchId="a",
            source="manual",
            status="completed",
            finishedAt=datetime.utcnow().isoformat() + "Z",
            rules=[{"id": 1, "name": "test"}],
        )
        publish(db, "a", [outcome], metadata)
        assert db.scalar(select(ScanCandidate)).status == "normal"
        db.get(ScanTask, "scan").status = "running"
        db.commit()
        bad = dict(values, indicators={"bad": object()})
        try:
            publish(
                db, "a", [Outcome("TEST", candidates=[bad], rules={1: ("normal", None)})], metadata
            )
        except StatementError:
            db.rollback()
        else:
            raise AssertionError("serialization failure did not roll back")
        assert db.scalar(select(ScanCandidate)).indicators == {"test.value": 10}
        assert db.get(ScanPublication, 1).metadata_json["normalCount"] == 1
print(
    "MySQL temporary-table checks passed: range sync, adjustment, actual turnover, "
    "invalid rollback, atomic publication rollback; no persistent rows changed"
)
