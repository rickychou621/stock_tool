SET NAMES utf8mb4;

SET @column_exists = (
    SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'market_scan_settings'
      AND COLUMN_NAME = 'large_stop_distance_pct'
);
SET @ddl = IF(@column_exists = 0,
    'ALTER TABLE market_scan_settings ADD COLUMN large_stop_distance_pct DOUBLE NULL',
    'SELECT 1');
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
