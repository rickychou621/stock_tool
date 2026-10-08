-- 少量示範資料，供前端頁面串接測試用。股價K線資料另外放在 003_seed_prices.sql
-- (用固定亂數種子產生的假走勢，非真實股價)。

SET NAMES utf8mb4;

INSERT INTO stocks (ticker, name, market, is_active) VALUES
    ('2330', '台積電', '上市', TRUE),
    ('2317', '鴻海', '上市', TRUE),
    ('2454', '聯發科', '上市', TRUE),
    ('2308', '台達電', '上市', TRUE),
    ('3034', '聯詠', '上市', TRUE),
    ('2412', '中華電', '上市', TRUE),
    ('2603', '長榮', '上市', TRUE)
ON DUPLICATE KEY UPDATE name = VALUES(name);

INSERT INTO condition_catalog (id, name, description, required_timeframe, update_frequency, param_schema) VALUES
    ('ema_golden_cross', 'EMA黃金交叉', 'EMA短週期上穿長週期', '分K', 'realtime', JSON_OBJECT('short_period', 'int', 'long_period', 'int')),
    ('bollinger_mid_up', '布林上軌區間(月線上揚)', '月線(20日中軌)上揚，且收盤未跌破月線；突破布林上軌仍符合。符合代表偏多型態，不代表立即進場', '日K', 'daily', JSON_OBJECT('period', 'int', 'num_std', 'float', 'slope_lookback', 'int')),
    ('kd_golden_cross', 'KD黃金交叉', 'K值上穿D值', '月K', 'monthly', JSON_OBJECT()),
    ('macd_positive', 'MACD轉正', 'DIF與MACD值皆大於0', '月K', 'monthly', JSON_OBJECT()),
    ('macd_histogram_rising', 'MACD動能增強(柱狀體上升)', 'MACD柱狀體(DIF-訊號線)較上月增加：綠柱縮減或紅柱增加', '月K', 'monthly', JSON_OBJECT('short_period', 'int', 'long_period', 'int', 'signal_period', 'int')),
    ('volume_spike', '爆量', '成交量超過近期均量的指定倍數', '日K', 'daily', JSON_OBJECT('multiplier', 'float'))
ON DUPLICATE KEY UPDATE name = VALUES(name);

INSERT INTO watch_rules (id, name, logic_operator, is_enabled) VALUES
    (1, '戰法二：布林上軌區間', 'AND', TRUE),
    (2, '戰法三：長波佈局', 'AND', TRUE),
    (3, 'A+B組合監控', 'AND', FALSE)
ON DUPLICATE KEY UPDATE name = VALUES(name);

INSERT INTO watch_rule_conditions (rule_id, condition_id, params, sort_order) VALUES
    (1, 'bollinger_mid_up', JSON_OBJECT('period', 20), 0),
    (2, 'kd_golden_cross', JSON_OBJECT(), 0),
    (2, 'macd_positive', JSON_OBJECT(), 1),
    (2, 'macd_histogram_rising', JSON_OBJECT(), 2),
    (3, 'ema_golden_cross', JSON_OBJECT('short_period', 10, 'long_period', 60), 0),
    (3, 'bollinger_mid_up', JSON_OBJECT('period', 20), 1);

INSERT INTO candidate_pool (ticker, reason, added_at, expired_at) VALUES
    ('2308', '成交量較均量放大3.2倍', NOW() - INTERVAL 2 HOUR, NULL),
    ('3034', '三大法人買超連續3日', NOW() - INTERVAL 1 HOUR, NULL),
    ('2412', '均線多頭排列(5>10>20)', NOW() - INTERVAL 30 MINUTE, NULL);

INSERT INTO holdings_watchlist (ticker, entry_price, entry_date, notes, is_active) VALUES
    ('2330', 918.00, CURDATE() - INTERVAL 9 DAY, '戰法一進場，防守10ema下穿60ema', TRUE),
    ('2317', 102.50, CURDATE() - INTERVAL 14 DAY, '戰法三進場，追蹤月K KD', TRUE);

INSERT INTO alerts_log (rule_id, ticker, triggered_at, price_at_trigger, message, is_notified) VALUES
    (1, '2330', NOW() - INTERVAL 2 HOUR, 1031.00, '2330 觸發戰法二：布林上軌區間', TRUE),
    (2, '2317', NOW() - INTERVAL 3 HOUR, 104.50, '2317 觸發戰法三：長波佈局', TRUE);
