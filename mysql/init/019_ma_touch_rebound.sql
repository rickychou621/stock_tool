-- Additive and repeatable; does not change strategy assignments.
SET NAMES utf8mb4;

INSERT INTO condition_catalog (id, name, description, required_timeframe, update_frequency, param_schema) VALUES
    ('ma_touch_rebound', '回到月線後轉強', '前一根最低價不高於當日月線乘以1加容許偏離且收盤不低於月線，今日收盤高於前一根且不低於今日月線', '日K', 'daily', JSON_OBJECT('period', 'int', 'tolerance', 'float'))
ON DUPLICATE KEY UPDATE
    name = VALUES(name),
    description = VALUES(description),
    required_timeframe = VALUES(required_timeframe),
    update_frequency = VALUES(update_frequency),
    param_schema = VALUES(param_schema);
