-- Additive and repeatable; strategy assignments are handled separately.
SET NAMES utf8mb4;

INSERT INTO condition_catalog (id, name, description, required_timeframe, update_frequency, param_schema) VALUES
    ('ma_rising', '月線上揚', '收盤簡單移動平均高於指定交易日前的均線；預設20日均線、回看5日', '日K', 'daily', JSON_OBJECT('period', 'int', 'slope_lookback', 'int')),
    ('price_touch_ma', '回到月線', '最低價不高於月線乘以1加容許偏離，且收盤不低於月線；預設20日均線、容許偏離0.01', '日K', 'daily', JSON_OBJECT('period', 'int', 'tolerance', 'float')),
    ('close_below_ma_days', '連續收盤跌破月線', '連續指定天數收盤低於各日自己的收盤簡單移動平均；預設20日均線、連續2日', '日K', 'daily', JSON_OBJECT('period', 'int', 'days', 'int'))
ON DUPLICATE KEY UPDATE
    name = VALUES(name),
    description = VALUES(description),
    required_timeframe = VALUES(required_timeframe),
    update_frequency = VALUES(update_frequency),
    param_schema = VALUES(param_schema);
