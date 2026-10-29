import type { ConditionCatalogItem, RuleCondition } from './types'

export const PERCENT_PARAMS = new Set([
  'tolerance',
  'buffer',
  'max_close_distance_pct',
  'min_slope_pct',
])
export const PARAM_LABELS: Record<string, string> = {
  period: '週期',
  slope_lookback: '斜率回看天數',
  tolerance: '容許範圍',
  days: '連續天數',
  buffer: '緩衝',
  threshold: '門檻',
  short_period: '短週期',
  long_period: '長週期',
  signal_period: '訊號週期',
  min_slope_pct: '月線斜率下限',
  max_close_distance_pct: '收盤距月線上限',
  max_k_at_cross: '交叉時 K 值上限',
}
export function inputValue(key: string, value: unknown): string {
  return typeof value === 'number'
    ? String(PERCENT_PARAMS.has(key) ? Number((value * 100).toPrecision(15)) : value)
    : ''
}
export function storedValue(key: string, value: string): number | null {
  return value === '' ? null : Number(value) / (PERCENT_PARAMS.has(key) ? 100 : 1)
}
export function displayValue(key: string, value: unknown): string {
  return value == null ? '不限制' : `${inputValue(key, value)}${PERCENT_PARAMS.has(key) ? '%' : ''}`
}
export function differingParams(
  params: Record<string, unknown>,
  defaults: Record<string, number | null>,
): string[] {
  return Object.keys(defaults).filter(
    (key) => Object.hasOwn(params, key) && params[key] !== defaults[key],
  )
}
export function formValues(
  condition: RuleCondition,
  catalog: ConditionCatalogItem,
  restore = false,
): Record<string, string> {
  return Object.fromEntries(
    Object.keys(catalog.paramSchema).map((key) => [
      key,
      inputValue(
        key,
        restore || !Object.hasOwn(condition.params, key)
          ? catalog.originalDefaults[key]
          : condition.params[key],
      ),
    ]),
  )
}
