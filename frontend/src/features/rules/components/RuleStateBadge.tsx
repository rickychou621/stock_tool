import { STATE_LABELS, type RuleStateCode, type RuleStateDetail } from '../state'

export function RuleStateBadge({
  ruleName,
  state,
  label,
}: {
  ruleName: string
  state: RuleStateCode
  label?: string
}) {
  return (
    <span
      className={`state-badge state-badge--${state.toLowerCase()}`}
      title={label ?? STATE_LABELS[state]}
    >
      {ruleName}：{label ?? STATE_LABELS[state]}
    </span>
  )
}

export function RuleStateLine({
  state,
  dataDate,
}: {
  state: RuleStateDetail
  dataDate?: string | null
}) {
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
          （觸價 {state.triggerPrice}，現價 {state.close ?? '—'}
          {dataDate && `（${dataDate.slice(5).replace('-', '/')}）`}，距離 {distance}%）
        </>
      )}
      {state.maDistancePct != null && `｜距月線 ${signedPct(state.maDistancePct, 1)}%`}
      {state.maSlopePct != null && `｜月線斜率 ${signedPct(state.maSlopePct, 2)}%／5 日`}
    </p>
  )
}
