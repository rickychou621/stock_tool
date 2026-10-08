import { outcome, OUTCOME_LABELS, type SavedEvaluation } from '../types'
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
  const status = error ? 'error' : outcome(results, expected)
  const matchedResults = results.filter((r) => !r.stale && r.result.isMet)
  const passed = matchedResults.length
  const visibleResults = passed ? matchedResults : results
  const upperBandMarks = [...new Set(
    visibleResults.filter((r) => !r.stale).flatMap((r) =>
      r.result.conditionResults.flatMap((c) => c.upperBandStatus ? [c.upperBandStatus] : []),
    ),
  )]
  const unresolved = results.filter(
    (r) => r.result.status === 'error' || r.result.status === 'insufficient_data',
  ).length
  return (
    <div className="evaluation-cell" aria-live="polite">
      <div className="evaluation-actions">
        <strong className={`evaluation-badge evaluation-badge--${busy ? 'pending' : status}`}>
          <span aria-hidden="true">
            {busy ? '…' : status === 'matched' ? '✓' : status === 'not_met' ? '×' : '!'}
          </span>
          {busy ? '更新行情並評估中' : OUTCOME_LABELS[status]}
        </strong>
        <button
          className="button-secondary"
          type="button"
          disabled={disabled || !expected}
          onClick={onEvaluate}
        >
          {results.length ? '重新評估' : '評估'}
        </button>
      </div>
      {!busy && !error && upperBandMarks.map((mark) => (
        <span className="upper-band-mark" key={mark}>
          {mark === 'breakout' ? '突破上軌' : '觸及上軌'} · 壓力參考
        </span>
      ))}
      {!!results.length && (
        <span className="muted">
          {passed}／{expected} 條通過
          {results.length < expected ? ` · ${expected - results.length} 條未評估` : ''}
          {unresolved ? ` · ${unresolved} 條待確認` : ''}
        </span>
      )}
      {status === 'stale' && (
        <span className="stale-notice">行情或戰法已更新，以下為上次結果。</span>
      )}
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
          <summary>{passed ? '通過戰法與評估時間' : '戰法結果與評估時間'}</summary>
          {visibleResults.map((r) => (
            <div className="rule-result" key={r.ruleId}>
              <strong>
                {r.ruleName} · {OUTCOME_LABELS[r.result.status]}
                {r.stale ? '（舊結果）' : ''}
              </strong>
              <p className="muted">
                行情：{r.result.dataDate ?? '無資料'} · 評估：
                {new Date(r.evaluatedAt).toLocaleString('zh-TW')}
              </p>
              <ul>
                {r.result.conditionResults.map((c, i) => (
                  <li key={i}>{c.reason}</li>
                ))}
              </ul>
            </div>
          ))}
        </details>
      )}
    </div>
  )
}
