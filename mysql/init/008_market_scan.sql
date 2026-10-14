SET NAMES utf8mb4;
-- Re-runnable additive migration; existing OHLC/history is preserved.
SET @has_turnover = (SELECT COUNT(*) FROM information_schema.COLUMNS
 WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='stock_price_daily' AND COLUMN_NAME='turnover');
SET @ddl = IF(@has_turnover=0, 'ALTER TABLE stock_price_daily ADD COLUMN turnover DECIMAL(22,2) NULL', 'SELECT 1');
PREPARE migration_statement FROM @ddl;
EXECUTE migration_statement;
DEALLOCATE PREPARE migration_statement;
CREATE TABLE IF NOT EXISTS market_scan_candidates (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	ticker VARCHAR(10) NOT NULL, 
	stock_name VARCHAR(50) NOT NULL, 
	kind VARCHAR(20) NOT NULL, 
	rule_id INTEGER NOT NULL, 
	rule_name VARCHAR(100) NOT NULL, 
	batch_id VARCHAR(36) NOT NULL, 
	status VARCHAR(30) NOT NULL, 
	reason VARCHAR(2000) NOT NULL, 
	status_reason VARCHAR(1000), 
	indicators JSON NOT NULL, 
	close NUMERIC(14, 4) NOT NULL, 
	price_date DATE NOT NULL, 
	volume BIGINT NOT NULL, 
	turnover NUMERIC(22, 2), 
	scanned_at DATETIME NOT NULL, 
	older_quote BOOL NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (ticker, rule_id),
INDEX ix_market_scan_candidates_close (close),
INDEX ix_market_scan_candidates_turnover (turnover),
INDEX ix_market_scan_candidates_ticker (ticker),
INDEX ix_market_scan_candidates_kind (kind),
INDEX ix_market_scan_candidates_rule_id (rule_id),
INDEX ix_market_scan_candidates_status (status),
INDEX ix_market_scan_candidates_batch_id (batch_id),
INDEX ix_market_scan_candidates_volume (volume),
INDEX ix_market_scan_candidates_price_date (price_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS market_scan_coverage (
	ticker VARCHAR(10) NOT NULL, 
	ranges JSON NOT NULL, 
	PRIMARY KEY (ticker)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS market_scan_errors (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	kind VARCHAR(16) NOT NULL, 
	batch_id VARCHAR(36) NOT NULL, 
	ticker VARCHAR(10), 
	rule_id INTEGER, 
	status VARCHAR(30) NOT NULL, 
	reason VARCHAR(1000) NOT NULL, 
	PRIMARY KEY (id),
INDEX ix_market_scan_errors_kind (kind)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS market_scan_publication (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	metadata_json JSON NOT NULL, 
	PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS market_scan_settings (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	enabled BOOL NOT NULL, 
	rule_ids JSON, 
	last_attempt_date DATE, 
	PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS market_scan_tasks (
	kind VARCHAR(16) NOT NULL, 
	batch_id VARCHAR(36) NOT NULL, 
	source VARCHAR(16) NOT NULL, 
	status VARCHAR(30) NOT NULL, 
	started_at DATETIME NOT NULL, 
	finished_at DATETIME, 
	baseline DATE, 
	rules JSON NOT NULL, 
	total INTEGER NOT NULL, 
	processed INTEGER NOT NULL, 
	succeeded INTEGER NOT NULL, 
	failed INTEGER NOT NULL, 
	insufficient INTEGER NOT NULL, 
	warnings JSON NOT NULL, 
	PRIMARY KEY (kind)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS market_scan_indicators (
	candidate_id INTEGER NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	value FLOAT NOT NULL, 
	PRIMARY KEY (candidate_id, name), 
	FOREIGN KEY(candidate_id) REFERENCES market_scan_candidates (id) ON DELETE CASCADE,
INDEX ix_market_scan_indicators_value (value)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS market_scan_instruments (
	ticker VARCHAR(10) NOT NULL, 
	market VARCHAR(20) NOT NULL, 
	kind VARCHAR(20) NOT NULL, 
	listed_on DATE NOT NULL, 
	active BOOL NOT NULL, 
	PRIMARY KEY (ticker), 
	FOREIGN KEY(ticker) REFERENCES stocks (ticker),
INDEX ix_market_scan_instruments_active (active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
INSERT IGNORE INTO market_scan_settings (id,enabled,rule_ids) VALUES (1,TRUE,NULL);
