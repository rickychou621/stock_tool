export type RuleStateCode = 'ENTRY' | 'HOLD' | 'NEAR_EXIT' | 'EXIT' | 'NONE' | 'NO_DATA' | 'STALE'

export interface RuleStateDetail {
  state: RuleStateCode
  reason: string
  triggerPrice: number | null
  close: number | null
  distancePct: number | null
}

export const STATE_LABELS: Record<RuleStateCode, string> = {
  EXIT: '出場',
  NEAR_EXIT: '接近出場',
  ENTRY: '進場',
  HOLD: '續抱',
  STALE: '需重新評估',
  NO_DATA: '資料不足',
  NONE: '不符合',
}

export const STATE_URGENCY: Record<RuleStateCode, number> = {
  EXIT: 0,
  NEAR_EXIT: 1,
  ENTRY: 2,
  HOLD: 3,
  STALE: 4,
  NO_DATA: 5,
  NONE: 6,
}

export function mostUrgent(states: RuleStateCode[]): RuleStateCode | null {
  return states.reduce<RuleStateCode | null>(
    (current, state) =>
      current === null || STATE_URGENCY[state] < STATE_URGENCY[current] ? state : current,
    null,
  )
}
