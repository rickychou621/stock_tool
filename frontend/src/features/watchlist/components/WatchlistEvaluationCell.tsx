import { useStopDistanceThreshold } from '../../rules/useStopDistanceThreshold'
import { isLargeStopDistance } from '../../rules/ruleMetrics'
import { formatDataDate, WEEKLY_DATA_DATE_TITLE } from '../../rules/dataDate'
import { formatTaipeiTime } from '../../../lib/time'
import type { SavedEvaluation } from '../types'
import { STATE_LABELS } from '../../rules/state'
import { RuleStateBadge, RuleStateLine } from '../../rules/components/RuleStateBadge'
const ROLE_LABELS = { premise: '前提', entry: '進場', exit: '出場' }
interface Props {
  results: SavedEvaluation[]
  busy: boolean
  error?: string
}
export function WatchlistEvaluationCell({
  results,
  busy,
  error,
}: Props) {
  const stopDistanceThreshold = useStopDistanceThreshold()
  const dailyResults = results.filter((r) => r.evaluationFrequency !== 'weekly')
  const dateResults = dailyResults.length ? dailyResults : results
  const dateFrequency = dailyResults.length ? 'daily' : 'weekly'
  const dataDate = dateResults
    .map((r) => r.result.dataDate)
    .filter((d): d is string => !!d)
    .sort()
    .at(-1)
  const staleResults = results.filter((r) => r.marketDataStale)
  const staleTitle = staleResults
    .map(
      (r) =>
        `最後行情 ${r.result.dataDate ?? '無資料'}，最近交易日 ${r.expectedDataDate ?? '無資料'}`,
    )
    .join('；')
  const dateTitle = [staleTitle, dateFrequency === 'weekly' ? WEEKLY_DATA_DATE_TITLE : '']
    .filter(Boolean)
    .join('；')
  const upperBandMarks = [
    ...new Set(
      results
        .filter((r) => r.state !== 'STALE')
        .flatMap((r) =>
          r.result.conditionResults.flatMap((c) => (c.upperBandStatus ? [c.upperBandStatus] : [])),
        ),
    ),
  ]
  return (
    <div className="evaluation-cell" aria-live="polite">
      <div className="rule-state-list">
        {results.map((r) => (
          <div className="rule-state-item" key={r.ruleId}>
            <RuleStateBadge ruleName={r.ruleName} state={r.state} />
            {r.state === 'ENTRY' && isLargeStopDistance(r.result.state?.stopDistancePct, stopDistanceThreshold) && (
              <span className="status-badge status-warning">停損距離大</span>
            )}
            {r.state === 'STALE' ? (
              <p className="stale-notice">行情或戰法已更新，請重新評估</p>
            ) : r.result.state ? (
              <RuleStateLine
                state={{ ...r.result.state, state: r.state }}
                dataDate={r.result.dataDate}
                evaluationFrequency={r.evaluationFrequency}
              />
            ) : (
              <p className="muted">{STATE_LABELS[r.state]}：尚無狀態說明</p>
            )}
          </div>
        ))}
      </div>
      {busy && <span role="status">更新行情並評估中…</span>}
      {!results.length && <span className="muted">尚未評估</span>}
      {dataDate && (
        <p title={dateTitle || undefined}>
          <span className={staleResults.length ? 'stale-notice' : undefined}>
            {dateFrequency === 'daily' ? '行情 ' : ''}{formatDataDate(dataDate, dateFrequency, 'MM/DD')}
          </span>
          {!!staleResults.length && <span className="status-badge status-warning">行情過期</span>}
        </p>
      )}
      {!busy &&
        !error &&
        upperBandMarks.map((mark) => (
          <span className="upper-band-mark" key={mark}>
            {mark === 'breakout' ? '突破上軌' : '觸及上軌'} · 壓力參考
          </span>
        ))}
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
      {error && !!results.length && (
        <span className="stale-notice">以下為上次保存結果，本次請求未完成。</span>
      )}
      {!!results.length && (
        <details className="evaluation-details">
          <summary>戰法結果與評估時間</summary>
          {results.map((r) => (
            <div className="rule-result" key={r.ruleId}>
              <strong>
                {r.ruleName} · {STATE_LABELS[r.state]}
                {r.state === 'STALE' ? '（舊結果）' : ''}
              </strong>
              <p className="muted">
                行情：{formatDataDate(r.result.dataDate, r.evaluationFrequency)} · 評估：
                {formatTaipeiTime(r.evaluatedAt)}
              </p>
              <ul>
                {r.result.conditionResults.map((c, i) => (
                  <li key={i}>
                    {c.role ? `${ROLE_LABELS[c.role]}：` : ''}
                    {c.reason}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </details>
      )}
    </div>
  )
}
