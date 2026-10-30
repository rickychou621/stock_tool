interface RuleMetrics {
  reason?: string
  maDistancePct?: number | null
  maSlopePct?: number | null
  stopDistancePct?: number | null
}

export function formatRuleMetrics({ maDistancePct, maSlopePct, stopDistancePct, reason = '' }: RuleMetrics): string[] {
  const signedPct = (value: number, digits: number) => {
    const rounded = Number(value.toFixed(digits))
    return `${rounded > 0 ? '+' : ''}${rounded.toFixed(digits)}`
  }
  return [
    maDistancePct == null || reason.includes('距月線') ? null : `距月線 ${signedPct(maDistancePct, 1)}%`,
    maSlopePct == null || reason.includes('月線斜率') ? null : `月線斜率 ${signedPct(maSlopePct, 2)}%／5 日`,
    stopDistancePct == null || reason.includes('停損距離') || reason.includes('距觸價') ? null : `停損距離 ${signedPct(stopDistancePct, 1)}%`,
  ].filter((value): value is string => value !== null)
}

export function isLargeStopDistance(
  stopDistancePct: number | null | undefined,
  thresholdPct: number,
): boolean {
  return stopDistancePct != null && Math.abs(stopDistancePct) > thresholdPct
}
