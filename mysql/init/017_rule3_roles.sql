-- Stage with C3 weekly evaluation; do not apply before C3 is ready.
SET NAMES utf8mb4;

START TRANSACTION;

INSERT INTO condition_catalog (id, name, description, required_timeframe, update_frequency, param_schema) VALUES
    ('kd_high_death_cross', 'KD 高檔死亡交叉', '本月KD死亡交叉且上月K不低於門檻；預設period=9、threshold=70', '月K', 'monthly', JSON_OBJECT('period', 'int', 'threshold', 'float')),
    ('macd_negative_any', 'MACD 轉負', '月K DIF或MACD訊號線任一小於0；預設12/26/9', '月K', 'monthly', JSON_OBJECT('short_period', 'int', 'long_period', 'int', 'signal_period', 'int'))
ON DUPLICATE KEY UPDATE
    name = VALUES(name),
    description = VALUES(description),
    required_timeframe = VALUES(required_timeframe),
    update_frequency = VALUES(update_frequency),
    param_schema = VALUES(param_schema);

DELETE FROM watch_rule_conditions WHERE rule_id = 2;

INSERT INTO watch_rule_conditions (rule_id, condition_id, params, sort_order, role)
SELECT 2, 'macd_positive', JSON_OBJECT(), 0, 'premise'
FROM watch_rules WHERE id = 2;

INSERT INTO watch_rule_conditions (rule_id, condition_id, params, sort_order, role)
SELECT 2, 'kd_golden_cross', JSON_OBJECT(), 1, 'entry'
FROM watch_rules WHERE id = 2;

INSERT INTO watch_rule_conditions (rule_id, condition_id, params, sort_order, role)
SELECT 2, 'kd_high_death_cross', JSON_OBJECT('period', 9, 'threshold', 70), 2, 'exit'
FROM watch_rules WHERE id = 2;

INSERT INTO watch_rule_conditions (rule_id, condition_id, params, sort_order, role)
SELECT 2, 'macd_negative_any', JSON_OBJECT(), 3, 'exit'
FROM watch_rules WHERE id = 2;

COMMIT;
