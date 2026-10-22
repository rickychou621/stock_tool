import { STATE_LABELS, type RuleStateCode, type RuleStateDetail } from '../state'

export function RuleStateBadge({ ruleName, state }: { ruleName: string; state: RuleStateCode }) {
  return (
    <span className={`state-badge state-badge--${state.toLowerCase()}`} title={STATE_LABELS[state]}>
      {ruleName} {state}
    </span>
  )
}

export function RuleStateLine({ state }: { state: RuleStateDetail }) {
  const distance =
    state.distancePct === null ? '—' : Number(state.distancePct.toFixed(1)).toFixed(1)
  const signedPct = (value: number, digits: number) => {
    const rounded = Number(value.toFixed(digits))
    return `${rounded > 0 ? '+' : ''}${rounded.toFixed(digits)}`
  }
  return (
    <p className="rule-state-line">
      {STATE_LABELS[state.state]}：{state.reason}
      {state.triggerPrice !== null && (
        <>
          （觸價 {state.triggerPrice}，現價 {state.close ?? '—'}，距離 {distance}%）
        </>
      )}
      {state.maDistancePct != null && `｜距月線 ${signedPct(state.maDistancePct, 1)}%`}
      {state.maSlopePct != null && `｜月線斜率 ${signedPct(state.maSlopePct, 2)}%／5 日`}
    </p>
  )
}
