-- Additive and repeatable; no data or schedule changes.
CREATE TABLE IF NOT EXISTS stock_price_events (
    id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    ticker VARCHAR(10) NOT NULL,
    event_date DATE NOT NULL,
    event_type VARCHAR(24) NOT NULL,
    before_close DECIMAL(14,6) NOT NULL,
    reference_price DECIMAL(14,6) NOT NULL,
    source VARCHAR(32) NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_price_event (ticker, event_date, event_type),
    KEY ix_stock_price_events_ticker (ticker),
    FOREIGN KEY (ticker) REFERENCES stocks(ticker)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS stock_price_event_sync (
    id INT NOT NULL PRIMARY KEY,
    synced_on DATE NOT NULL,
    complete BOOLEAN NOT NULL DEFAULT FALSE,
    CONSTRAINT ck_price_event_sync_singleton CHECK (id = 1)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
