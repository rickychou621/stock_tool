SET @has_context = (SELECT COUNT(*) FROM information_schema.COLUMNS
 WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='backtest_latest_task' AND COLUMN_NAME='context_json');
SET @ddl = IF(@has_context=0,
 'ALTER TABLE backtest_latest_task ADD COLUMN context_json JSON NULL', 'SELECT 1');
PREPARE migration_statement FROM @ddl;
EXECUTE migration_statement;
DEALLOCATE PREPARE migration_statement;
