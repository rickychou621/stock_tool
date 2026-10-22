-- Requires 021_alert_state.sql before applying.
SET NAMES utf8mb4;

SET @etf_category_sql = (
    SELECT IF(COUNT(*) = 0,
        'ALTER TABLE market_scan_instruments ADD COLUMN etf_category VARCHAR(16) NULL AFTER kind',
        'SELECT 1')
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'market_scan_instruments'
      AND COLUMN_NAME = 'etf_category'
);
PREPARE etf_category_statement FROM @etf_category_sql;
EXECUTE etf_category_statement;
DEALLOCATE PREPARE etf_category_statement;

UPDATE market_scan_instruments
SET etf_category = CASE RIGHT(ticker, 1)
    WHEN 'L' THEN 'leveraged'
    WHEN 'R' THEN 'inverse'
    WHEN 'B' THEN 'bond'
    WHEN 'D' THEN 'bond'
    WHEN 'U' THEN 'futures'
    ELSE 'equity'
END
WHERE kind = 'etf';
