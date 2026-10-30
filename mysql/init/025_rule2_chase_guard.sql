SET NAMES utf8mb4;

START TRANSACTION;

UPDATE watch_rules
SET updated_at = UTC_TIMESTAMP()
WHERE id IN (
    SELECT rule_id FROM watch_rule_conditions
    WHERE (condition_id = 'ma_rising'
           AND JSON_CONTAINS_PATH(params, 'one', '$.min_slope_pct') = 0)
       OR (condition_id = 'ma_touch_rebound'
           AND JSON_CONTAINS_PATH(params, 'one', '$.max_close_distance_pct') = 0)
);

UPDATE watch_rule_conditions
SET params = JSON_SET(params, '$.min_slope_pct', 0.005)
WHERE condition_id = 'ma_rising'
  AND JSON_CONTAINS_PATH(params, 'one', '$.min_slope_pct') = 0;

UPDATE watch_rule_conditions
SET params = JSON_SET(params, '$.max_close_distance_pct', 0.03)
WHERE condition_id = 'ma_touch_rebound'
  AND JSON_CONTAINS_PATH(params, 'one', '$.max_close_distance_pct') = 0;

COMMIT;
