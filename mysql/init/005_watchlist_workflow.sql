SET NAMES utf8mb4;
ALTER TABLE stocks ADD COLUMN sector VARCHAR(80) NOT NULL DEFAULT '',
                   ADD COLUMN data_version INT NOT NULL DEFAULT 0;
CREATE TABLE IF NOT EXISTS watchlist_evaluations (
    id INT AUTO_INCREMENT PRIMARY KEY,
    item_id INT NOT NULL,
    rule_id INT NOT NULL,
    result JSON NOT NULL,
    evaluated_at DATETIME NOT NULL,
    data_version INT NOT NULL,
    rule_fingerprint VARCHAR(64) NOT NULL,
    UNIQUE KEY uq_watchlist_evaluation (item_id, rule_id),
    FOREIGN KEY (item_id) REFERENCES holdings_watchlist(id) ON DELETE CASCADE,
    FOREIGN KEY (rule_id) REFERENCES watch_rules(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
UPDATE stocks SET sector = CASE
 WHEN ticker IN ('2330','3711','3481','2409') THEN '台積電及相關先進封裝'
 WHEN ticker IN ('6182','3532','6488','3016') THEN '矽晶圓'
 WHEN ticker IN ('3105','2455','8086') THEN '砷化鎵'
 WHEN ticker IN ('6274','6213','2383') THEN '銅箔基板 CCL'
 WHEN ticker IN ('3026','6173') THEN '被動元件'
 WHEN ticker IN ('3037','3189','8046') THEN 'ABF 載板'
 ELSE sector END WHERE sector = '';
