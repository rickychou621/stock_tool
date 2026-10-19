-- Stage 4 A only. B/C are deferred. Safe to apply repeatedly.
CREATE TABLE IF NOT EXISTS market_scan_batch_coverage (
    trade_date DATE NOT NULL PRIMARY KEY,
    absent_tickers JSON NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Date-first coverage queries must not scan the complete history every day.
SET @has_day_index = (SELECT COUNT(*) FROM information_schema.STATISTICS
 WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='stock_price_daily'
 AND INDEX_NAME='ix_stock_price_daily_trade_date');
SET @ddl = IF(@has_day_index=0,
 'ALTER TABLE stock_price_daily ADD INDEX ix_stock_price_daily_trade_date (trade_date)',
 'SELECT 1');
PREPARE migration_statement FROM @ddl;
EXECUTE migration_statement;
DEALLOCATE PREPARE migration_statement;
