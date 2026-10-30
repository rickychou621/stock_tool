import { formatDataDate, WEEKLY_DATA_DATE_TITLE } from '../dataDate'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import {
  faClock,
  faMinus,
  faPersonShelter,
  faPersonWalkingArrowRight,
  faPersonWalkingDashedLineArrowRight,
  faQuestion,
  faRightToBracket,
} from '@fortawesome/free-solid-svg-icons'
import type { IconDefinition } from '@fortawesome/fontawesome-svg-core'
import { STATE_LABELS, type RuleStateCode, type RuleStateDetail } from '../state'

const STATE_ICONS: Record<RuleStateCode, IconDefinition> = {
  ENTRY: faRightToBracket,
  HOLD: faPersonShelter,
  NEAR_EXIT: faPersonWalkingDashedLineArrowRight,
  EXIT: faPersonWalkingArrowRight,
  NONE: faMinus,
  NO_DATA: faQuestion,
  STALE: faClock,
}

export function RuleStateBadge({
  ruleName,
  state,
  label,
}: {
  ruleName: string
  state: RuleStateCode
  label?: string
}) {
  const text = label ?? STATE_LABELS[state]
  return (
    <span
      className={`state-badge state-badge--${state.toLowerCase()}`}
      title={`${ruleName}：${text}`}
    >
      <span>{ruleName}</span>
      <span className="state-badge__state">
        <FontAwesomeIcon icon={label === '行情過期' ? faClock : STATE_ICONS[state]} />
        {text}
      </span>
    </span>
  )
}

export function RuleStateLine({
  state,
  dataDate,
  evaluationFrequency = 'daily',
}: {
  state: RuleStateDetail
  dataDate?: string | null
  evaluationFrequency?: string
}) {
  const distance =
    state.distancePct === null ? '—' : Number(state.distancePct.toFixed(1)).toFixed(1)
  const signedPct = (value: number, digits: number) => {
    const rounded = Number(value.toFixed(digits))
    return `${rounded > 0 ? '+' : ''}${rounded.toFixed(digits)}`
  }
  return (
    <p
      className="rule-state-line"
      title={evaluationFrequency === 'weekly' ? WEEKLY_DATA_DATE_TITLE : undefined}
    >
      {STATE_LABELS[state.state]}：{state.reason}
      {state.triggerPrice !== null && (
        <>
          （觸價 {state.triggerPrice}，現價 {state.close ?? '—'}
          {dataDate && `（${evaluationFrequency === 'weekly' ? '月 K 計算至 ' : ''}${formatDataDate(dataDate, 'daily', 'MM/DD')}）`}，距離 {distance}%）
        </>
      )}
      {state.maDistancePct != null && `｜距月線 ${signedPct(state.maDistancePct, 1)}%`}
      {state.maSlopePct != null && `｜月線斜率 ${signedPct(state.maSlopePct, 2)}%／5 日`}
    </p>
  )
}
