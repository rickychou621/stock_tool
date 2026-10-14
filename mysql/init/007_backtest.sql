SET NAMES utf8mb4;
CREATE TABLE IF NOT EXISTS backtest_latest_task (
 id INT PRIMARY KEY, batch_id VARCHAR(36) NOT NULL, status VARCHAR(30) NOT NULL,
 started_at DATETIME NOT NULL, finished_at DATETIME NULL,
 start_date DATE NOT NULL, end_date DATE NOT NULL,
 rule_ids JSON NOT NULL, tickers JSON NOT NULL,
 total INT NOT NULL DEFAULT 0, succeeded INT NOT NULL DEFAULT 0,
 failed INT NOT NULL DEFAULT 0, errors JSON NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS backtest_results (
 id INT AUTO_INCREMENT PRIMARY KEY, ticker VARCHAR(10) NOT NULL,
 stock_name VARCHAR(50) NOT NULL, rule_id INT NOT NULL, rule_name VARCHAR(100) NOT NULL,
 batch_id VARCHAR(36) NOT NULL, stale BOOLEAN NOT NULL DEFAULT FALSE,
 calculated_at DATETIME NOT NULL, summary JSON NOT NULL, payload JSON NOT NULL,
 UNIQUE KEY uq_backtest_pair (ticker, rule_id), INDEX ix_backtest_batch (batch_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS backtest_data_coverage (
 ticker VARCHAR(10) PRIMARY KEY, start_date DATE NOT NULL, end_date DATE NOT NULL,
 dates JSON NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS backtest_calendar_months (
 month VARCHAR(7) PRIMARY KEY, checked_on DATE NOT NULL, dates JSON NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
