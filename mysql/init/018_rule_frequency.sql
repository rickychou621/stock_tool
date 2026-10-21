-- Apply together with 017 after C3b is complete. Repeatable.
SET @has_frequency = (SELECT COUNT(*) FROM information_schema.COLUMNS
 WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='watch_rules' AND COLUMN_NAME='evaluation_frequency');
SET @ddl = IF(@has_frequency=0,
 'ALTER TABLE watch_rules ADD COLUMN evaluation_frequency VARCHAR(10) NOT NULL DEFAULT ''daily''',
 'SELECT 1');
PREPARE migration_statement FROM @ddl;
EXECUTE migration_statement;
DEALLOCATE PREPARE migration_statement;

UPDATE watch_rules SET evaluation_frequency='weekly' WHERE id=2;
