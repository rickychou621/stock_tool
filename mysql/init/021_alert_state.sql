-- Requires 020_rule2_a1b.sql before applying.
-- Repeatable; add the shared rule state without changing existing alerts.
SET NAMES utf8mb4;

SET @alert_state_sql = (
    SELECT IF(COUNT(*) = 0,
        'ALTER TABLE alerts_log ADD COLUMN state VARCHAR(16) NULL AFTER is_notified',
        'SELECT 1')
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'alerts_log'
      AND COLUMN_NAME = 'state'
);
PREPARE alert_state_statement FROM @alert_state_sql;
EXECUTE alert_state_statement;
DEALLOCATE PREPARE alert_state_statement;
