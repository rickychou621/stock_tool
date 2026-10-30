import re
import sqlite3
from pathlib import Path


def test_large_stop_distance_migration_repeatable_preserves_saved_value():
    sql = (Path(__file__).resolve().parents[3]
           / "mysql/init/026_large_stop_distance_setting.sql").read_text()
    assert "FROM information_schema.COLUMNS" in sql
    assert "TABLE_SCHEMA = DATABASE()" in sql
    assert "TABLE_NAME = 'market_scan_settings'" in sql
    assert "COLUMN_NAME = 'large_stop_distance_pct'" in sql
    assert "IF(@column_exists = 0," in sql
    ddl = re.search(r"'(ALTER TABLE [^']+)'", sql).group(1)
    assert ddl.endswith("large_stop_distance_pct DOUBLE NULL")
    with sqlite3.connect(":memory:") as db:
        db.execute("CREATE TABLE market_scan_settings (id INTEGER PRIMARY KEY)")
        db.execute("INSERT INTO market_scan_settings VALUES (1)")
        for value in (None, 0.08):
            # SQLite PRAGMA substitutes only the MySQL information_schema/prepare guard.
            columns = {row[1] for row in db.execute("PRAGMA table_info(market_scan_settings)")}
            if "large_stop_distance_pct" not in columns:
                db.execute(ddl)
            assert db.execute(
                "SELECT large_stop_distance_pct FROM market_scan_settings WHERE id = 1"
            ).fetchone()[0] == value
            db.execute("UPDATE market_scan_settings SET large_stop_distance_pct = 0.08")
