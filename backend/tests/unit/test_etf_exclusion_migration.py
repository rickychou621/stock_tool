import json
import re
import sqlite3
from pathlib import Path


def test_etf_exclusion_migration_repeatable_preserves_saved_selection():
    sql = (Path(__file__).resolve().parents[3]
           / "mysql/init/024_etf_exclusion_setting.sql").read_text()
    assert "FROM information_schema.COLUMNS" in sql
    assert "TABLE_SCHEMA = DATABASE()" in sql
    assert "TABLE_NAME = 'market_scan_settings'" in sql
    assert "COLUMN_NAME = 'excluded_etf_categories'" in sql
    assert "IF(@column_exists = 0," in sql
    ddl = re.search(r"'(ALTER TABLE [^']+)'", sql).group(1)
    update = sql[sql.index("UPDATE market_scan_settings"):]
    with sqlite3.connect(":memory:") as db:
        db.execute("CREATE TABLE market_scan_settings (id INTEGER PRIMARY KEY)")
        db.execute("INSERT INTO market_scan_settings VALUES (1), (2)")
        for _ in range(2):
            # SQLite PRAGMA substitutes only the MySQL information_schema/prepare guard.
            columns = {row[1] for row in db.execute("PRAGMA table_info(market_scan_settings)")}
            if "excluded_etf_categories" not in columns:
                db.execute(ddl)
            db.execute(update)
            value = db.execute(
                "SELECT excluded_etf_categories FROM market_scan_settings WHERE id = 1"
            ).fetchone()[0]
            assert json.loads(value) == ["leveraged", "inverse", "bond", "futures"]
            assert db.execute(
                "SELECT excluded_etf_categories FROM market_scan_settings WHERE id = 2"
            ).fetchone()[0] is None
        db.execute("UPDATE market_scan_settings SET excluded_etf_categories = '[]' WHERE id = 1")
        db.execute(update)
        assert db.execute(
            "SELECT excluded_etf_categories FROM market_scan_settings WHERE id = 1"
        ).fetchone()[0] == "[]"
