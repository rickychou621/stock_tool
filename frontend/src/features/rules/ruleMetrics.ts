interface RuleMetrics {
  maDistancePct?: number | null
  maSlopePct?: number | null
  stopDistancePct?: number | null
}

export function formatRuleMetrics({ maDistancePct, maSlopePct, stopDistancePct }: RuleMetrics): string[] {
  const signedPct = (value: number, digits: number) => {
    const rounded = Number(value.toFixed(digits))
    return `${rounded > 0 ? '+' : ''}${rounded.toFixed(digits)}`
  }
  return [
    maDistancePct == null ? null : `距月線 ${signedPct(maDistancePct, 1)}%`,
    maSlopePct == null ? null : `月線斜率 ${signedPct(maSlopePct, 2)}%／5 日`,
    stopDistancePct == null ? null : `停損距離 ${signedPct(stopDistancePct, 1)}%`,
  ].filter((value): value is string => value !== null)
}
