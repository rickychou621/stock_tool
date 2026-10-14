SET NAMES utf8mb4;
CREATE TABLE IF NOT EXISTS watchlist_schedule_settings (
    id INT PRIMARY KEY,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    rule_ids JSON NULL,
    last_attempt_date DATE NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
INSERT IGNORE INTO watchlist_schedule_settings (id, enabled) VALUES (1, TRUE);
CREATE TABLE IF NOT EXISTS watchlist_schedule_latest (
    id INT PRIMARY KEY,
    batch_id VARCHAR(36) NOT NULL,
    trade_date DATE NOT NULL,
    started_at DATETIME NOT NULL,
    finished_at DATETIME NULL,
    status VARCHAR(30) NOT NULL,
    total INT NOT NULL DEFAULT 0,
    succeeded INT NOT NULL DEFAULT 0,
    failed INT NOT NULL DEFAULT 0
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS watchlist_schedule_errors (
    id INT AUTO_INCREMENT PRIMARY KEY,
    batch_id VARCHAR(36) NOT NULL,
    ticker VARCHAR(10) NULL,
    occurred_at DATETIME NOT NULL,
    reason TEXT NOT NULL,
    INDEX ix_schedule_error_batch (batch_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
