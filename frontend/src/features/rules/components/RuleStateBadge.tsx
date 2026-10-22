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
  return (
    <p className="rule-state-line">
      {STATE_LABELS[state.state]}：{state.reason}
      {state.triggerPrice !== null && (
        <>
          （觸價 {state.triggerPrice}，現價 {state.close ?? '—'}，距離 {distance}%）
        </>
      )}
    </p>
  )
}
