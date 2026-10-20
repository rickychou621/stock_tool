-- Additive and repeatable; existing conditions remain premises.
SET @has_role = (SELECT COUNT(*) FROM information_schema.COLUMNS
 WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='watch_rule_conditions' AND COLUMN_NAME='role');
SET @ddl = IF(@has_role=0,
 'ALTER TABLE watch_rule_conditions ADD COLUMN role VARCHAR(10) NOT NULL DEFAULT ''premise''',
 'SELECT 1');
PREPARE migration_statement FROM @ddl;
EXECUTE migration_statement;
DEALLOCATE PREPARE migration_statement;
