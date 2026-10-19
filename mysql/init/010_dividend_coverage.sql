-- Additive, repeatable; no schedule changes.
CREATE TABLE IF NOT EXISTS market_scan_dividend_coverage (
    ticker VARCHAR(10) NOT NULL PRIMARY KEY,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
