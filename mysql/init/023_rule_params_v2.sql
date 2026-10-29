-- Repeatable; optional MA limits remain unset in rule params.
SET NAMES utf8mb4;

START TRANSACTION;

UPDATE condition_catalog
SET param_schema = JSON_SET(param_schema, '$.max_close_distance_pct', 'float')
WHERE id = 'ma_touch_rebound';

UPDATE condition_catalog
SET param_schema = JSON_SET(param_schema, '$.min_slope_pct', 'float')
WHERE id = 'ma_rising';

UPDATE condition_catalog
SET param_schema = JSON_SET(param_schema, '$.buffer', 'float')
WHERE id = 'close_below_ma_days';

UPDATE condition_catalog
SET param_schema = JSON_OBJECT('period', 'int', 'max_k_at_cross', 'float')
WHERE id = 'kd_golden_cross';

UPDATE watch_rule_conditions
SET params = JSON_OBJECT('period', 9, 'max_k_at_cross', 70)
WHERE rule_id = 2 AND condition_id = 'kd_golden_cross';

UPDATE watch_rules SET updated_at = UTC_TIMESTAMP() WHERE id = 2;

COMMIT;
