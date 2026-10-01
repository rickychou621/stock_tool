-- 資料表結構，對照 backend 的 SQLAlchemy models(見 docs/db.md)。
-- 只有在 mysql/data 是全新、空的volume時，docker-entrypoint-initdb.d 才會自動跑這個檔案；
-- 若容器已經跑過一次，改用 `docker exec` 手動執行這份SQL即可，不需要清空volume重來。

SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS stocks (
    id INT AUTO_INCREMENT PRIMARY KEY,
    ticker VARCHAR(10) NOT NULL UNIQUE,
    name VARCHAR(50) NOT NULL,
    market VARCHAR(10) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS stock_price_daily (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    ticker VARCHAR(10) NOT NULL,
    trade_date DATE NOT NULL,
    open DECIMAL(10, 2) NOT NULL,
    high DECIMAL(10, 2) NOT NULL,
    low DECIMAL(10, 2) NOT NULL,
    close DECIMAL(10, 2) NOT NULL,
    volume BIGINT NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_stock_price_daily (ticker, trade_date),
    CONSTRAINT fk_stock_price_daily_ticker FOREIGN KEY (ticker) REFERENCES stocks (ticker)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS stock_price_intraday (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    ticker VARCHAR(10) NOT NULL,
    timeframe VARCHAR(10) NOT NULL,
    bar_time DATETIME NOT NULL,
    open DECIMAL(10, 2) NOT NULL,
    high DECIMAL(10, 2) NOT NULL,
    low DECIMAL(10, 2) NOT NULL,
    close DECIMAL(10, 2) NOT NULL,
    volume BIGINT NOT NULL,
    UNIQUE KEY uq_stock_price_intraday (ticker, timeframe, bar_time),
    CONSTRAINT fk_stock_price_intraday_ticker FOREIGN KEY (ticker) REFERENCES stocks (ticker)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS condition_catalog (
    id VARCHAR(50) PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    description VARCHAR(500) NOT NULL DEFAULT '',
    required_timeframe VARCHAR(10) NOT NULL,
    update_frequency VARCHAR(10) NOT NULL,
    param_schema JSON NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS daily_condition_cache (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    ticker VARCHAR(10) NOT NULL,
    condition_id VARCHAR(50) NOT NULL,
    params_hash VARCHAR(64) NOT NULL,
    trade_date DATE NOT NULL,
    result BOOLEAN NOT NULL,
    computed_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_daily_condition_cache (ticker, condition_id, params_hash, trade_date),
    CONSTRAINT fk_daily_condition_cache_condition FOREIGN KEY (condition_id) REFERENCES condition_catalog (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS watch_rules (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    logic_operator VARCHAR(5) NOT NULL DEFAULT 'AND',
    is_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS watch_rule_conditions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    rule_id INT NOT NULL,
    condition_id VARCHAR(50) NOT NULL,
    params JSON NOT NULL,
    sort_order INT NOT NULL DEFAULT 0,
    CONSTRAINT fk_watch_rule_conditions_rule FOREIGN KEY (rule_id) REFERENCES watch_rules (id) ON DELETE CASCADE,
    CONSTRAINT fk_watch_rule_conditions_condition FOREIGN KEY (condition_id) REFERENCES condition_catalog (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS candidate_pool (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    ticker VARCHAR(10) NOT NULL,
    reason VARCHAR(255) NOT NULL DEFAULT '',
    score DECIMAL(10, 4) NULL,
    added_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expired_at DATETIME NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS holdings_watchlist (
    id INT AUTO_INCREMENT PRIMARY KEY,
    ticker VARCHAR(10) NOT NULL,
    entry_price DECIMAL(10, 2) NULL,
    entry_date DATE NULL,
    notes TEXT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS alerts_log (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    rule_id INT NOT NULL,
    ticker VARCHAR(10) NOT NULL,
    triggered_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    price_at_trigger DECIMAL(10, 2) NULL,
    message TEXT NOT NULL,
    is_notified BOOLEAN NOT NULL DEFAULT FALSE,
    INDEX ix_alerts_log_ticker_time (ticker, triggered_at),
    INDEX ix_alerts_log_rule_time (rule_id, triggered_at),
    CONSTRAINT fk_alerts_log_rule FOREIGN KEY (rule_id) REFERENCES watch_rules (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
