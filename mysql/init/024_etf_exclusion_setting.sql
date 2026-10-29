SET NAMES utf8mb4;

SET @column_exists = (
    SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'market_scan_settings'
      AND COLUMN_NAME = 'excluded_etf_categories'
);
SET @ddl = IF(@column_exists = 0,
    'ALTER TABLE market_scan_settings ADD COLUMN excluded_etf_categories JSON NULL',
    'SELECT 1');
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

UPDATE market_scan_settings
SET excluded_etf_categories = JSON_ARRAY('leveraged', 'inverse', 'bond', 'futures')
WHERE id = 1 AND excluded_etf_categories IS NULL;
