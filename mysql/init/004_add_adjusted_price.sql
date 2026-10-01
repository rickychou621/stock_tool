-- 新增還原股價欄位 + 股利事件表(見 docs/db.md 與 price_adjustment.py)。
-- 對已存在的資料庫要手動用 `docker exec` 套用；全新安裝的話 docker-entrypoint-initdb.d 會自動跑。

SET NAMES utf8mb4;

ALTER TABLE stock_price_daily
    ADD COLUMN adj_open DECIMAL(10, 2) NULL AFTER close,
    ADD COLUMN adj_high DECIMAL(10, 2) NULL AFTER adj_open,
    ADD COLUMN adj_low DECIMAL(10, 2) NULL AFTER adj_high,
    ADD COLUMN adj_close DECIMAL(10, 2) NULL AFTER adj_low;

CREATE TABLE IF NOT EXISTS stock_dividend_events (
    id INT AUTO_INCREMENT PRIMARY KEY,
    ticker VARCHAR(10) NOT NULL,
    ex_dividend_date DATE NOT NULL,
    cash_dividend DECIMAL(10, 4) NOT NULL DEFAULT 0,
    stock_dividend_ratio DECIMAL(10, 6) NOT NULL DEFAULT 0,
    cash_capital_increase_ratio DECIMAL(10, 6) NOT NULL DEFAULT 0,
    cash_capital_increase_price DECIMAL(10, 2) NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_stock_dividend_events (ticker, ex_dividend_date),
    CONSTRAINT fk_stock_dividend_events_ticker FOREIGN KEY (ticker) REFERENCES stocks (ticker)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
