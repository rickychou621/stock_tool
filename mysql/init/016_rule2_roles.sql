-- Repeatable; replace only strategy two conditions and preserve other strategies.
SET NAMES utf8mb4;

-- One transaction: a failed insert must not leave strategy two half-replaced.
START TRANSACTION;

DELETE FROM watch_rule_conditions WHERE rule_id = 1;

INSERT INTO watch_rule_conditions (rule_id, condition_id, params, sort_order, role)
SELECT 1, 'ma_rising', JSON_OBJECT('period', 20, 'slope_lookback', 5), 0, 'premise'
FROM watch_rules WHERE id = 1;

INSERT INTO watch_rule_conditions (rule_id, condition_id, params, sort_order, role)
SELECT 1, 'price_touch_ma', JSON_OBJECT('period', 20, 'tolerance', 0.01), 1, 'entry'
FROM watch_rules WHERE id = 1;

INSERT INTO watch_rule_conditions (rule_id, condition_id, params, sort_order, role)
SELECT 1, 'close_below_ma_days', JSON_OBJECT('period', 20, 'days', 2), 2, 'exit'
FROM watch_rules WHERE id = 1;

COMMIT;
