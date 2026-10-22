import type { SavedEvaluation } from '../types'
import { STATE_LABELS } from '../../rules/state'
import { RuleStateBadge, RuleStateLine } from '../../rules/components/RuleStateBadge'
const ROLE_LABELS = { premise: '前提', entry: '進場', exit: '出場' }
interface Props {
  results: SavedEvaluation[]
  expected: number
  disabled: boolean
  busy: boolean
  error?: string
  onEvaluate: () => void
}
export function WatchlistEvaluationCell({
  results,
  expected,
  disabled,
  busy,
  error,
  onEvaluate,
}: Props) {
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
      <div className="evaluation-actions">
        <button
          className="button-secondary"
          type="button"
          disabled={disabled || !expected}
          onClick={onEvaluate}
        >
          {results.length ? '重新評估' : '評估'}
        </button>
      </div>
      {busy && <span role="status">更新行情並評估中…</span>}
      {!results.length && <span className="muted">尚未評估</span>}
      <div className="rule-state-list">
        {results.map((r) => (
          <div className="rule-state-item" key={r.ruleId}>
            <RuleStateBadge ruleName={r.ruleName} state={r.state} />
            {r.state === 'STALE' ? (
              <p className="stale-notice">行情或戰法已更新，請重新評估</p>
            ) : r.result.state ? (
              <RuleStateLine state={{ ...r.result.state, state: r.state }} />
            ) : (
              <p className="muted">{STATE_LABELS[r.state]}：尚無狀態說明</p>
            )}
          </div>
        ))}
      </div>
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
                行情：{r.result.dataDate ?? '無資料'} · 評估：
                {new Date(r.evaluatedAt).toLocaleString('zh-TW')}
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
