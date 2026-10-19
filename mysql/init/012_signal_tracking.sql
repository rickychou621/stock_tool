-- Stage 4 B: additive and repeatable; no changes to schedules or old candidates.

CREATE TABLE IF NOT EXISTS market_scan_signal_history (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	signal_date DATE NOT NULL, 
	ticker VARCHAR(10) NOT NULL, 
	stock_name VARCHAR(50) NOT NULL, 
	rule_id INTEGER NOT NULL, 
	rule_name VARCHAR(100) NOT NULL, 
	kind VARCHAR(20) NOT NULL, 
	price_date DATE NOT NULL, 
	older_quote BOOL NOT NULL, 
	close NUMERIC(14, 4) NOT NULL, 
	volume BIGINT NOT NULL, 
	turnover NUMERIC(22, 2), 
	indicators JSON NOT NULL, 
	source VARCHAR(16) NOT NULL, 
	first_batch_id VARCHAR(36) NOT NULL, 
	last_batch_id VARCHAR(36) NOT NULL, 
	created_at DATETIME NOT NULL, 
	last_seen_at DATETIME NOT NULL, 
	cost_snapshot JSON NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (signal_date, ticker, rule_id),
INDEX ix_market_scan_signal_history_signal_date (signal_date),
INDEX ix_market_scan_signal_history_rule_id (rule_id),
INDEX ix_signal_rule_date (rule_id, signal_date),
INDEX ix_market_scan_signal_history_ticker (ticker)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS market_scan_signal_returns (
	signal_id INTEGER NOT NULL, 
	horizon INTEGER NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	reason VARCHAR(300), 
	values_json JSON NOT NULL, 
	PRIMARY KEY (signal_id, horizon), 
	FOREIGN KEY(signal_id) REFERENCES market_scan_signal_history (id),
INDEX ix_signal_horizon_status (horizon, status),
INDEX ix_market_scan_signal_returns_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS market_scan_signal_meta (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	deployed_on DATE NOT NULL, 
	PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT IGNORE INTO market_scan_signal_meta (id, deployed_on) VALUES (1, DATE(UTC_TIMESTAMP() + INTERVAL 8 HOUR));
