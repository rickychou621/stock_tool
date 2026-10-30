import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faFloppyDisk } from '@fortawesome/free-solid-svg-icons'
import { formatTaipeiTime, parseUtcTime } from '../../../lib/time'
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../../../api/client'
import type { WatchRule } from '../../rules/types'

type Settings = { enabled: boolean; ruleIds: number[] }
type Failure = {
  id: number
  ticker: string | null
  reason: string
  occurredAt: string
  batchId: string
}
type Run = {
  batchId: string
  tradeDate: string
  startedAt: string
  finishedAt: string | null
  status: string
  total: number
  succeeded: number
  failed: number
  errors: Failure[]
}
const statuses: Record<string, string> = {
  running: '執行中',
  succeeded: '完成',
  partial_failure: '部分失敗',
  failed: '失敗',
}

export function WatchlistSchedule({
  rules,
  lastEvaluatedAt,
}: {
  rules: WatchRule[] | undefined
  lastEvaluatedAt?: string | null
}) {
  const client = useQueryClient()
  const [draft, setDraft] = useState<Settings | null>(null)
  const settings = useQuery({
    queryKey: ['watchlist-schedule-settings'],
    queryFn: () => apiClient.get<Settings>('/watchlist-schedule/settings'),
    refetchOnWindowFocus: false,
  })
  const latest = useQuery({
    queryKey: ['watchlist-schedule-latest'],
    queryFn: () => apiClient.get<Run | null>('/watchlist-schedule/latest'),
    refetchOnWindowFocus: false,
  })
  const save = useMutation({
    mutationFn: (value: Settings) => apiClient.put<Settings>('/watchlist-schedule/settings', value),
    onSuccess: (value) => {
      client.setQueryData(['watchlist-schedule-settings'], value)
      setDraft(null)
    },
  })
  const value = draft ?? settings.data
  const run = latest.data
  // 自動更新也會寫評估時間；比自動更新結束還晚的才是手動評估
  const manualAt =
    lastEvaluatedAt &&
    (!run || parseUtcTime(lastEvaluatedAt) > parseUtcTime(run.finishedAt ?? run.startedAt))
      ? lastEvaluatedAt
      : null
  const change = (next: Settings) => {
    setDraft(next)
    save.reset()
  }
  return (
    <details
      className="card schedule-card"
      open={!!run && (run.errors.length > 0 || run.status === 'failed')}
    >
      <summary className="schedule-heading">
        <strong>每日自動更新</strong>
        <span className={`schedule-status ${settings.data?.enabled ? 'schedule-enabled' : ''}`}>
          {settings.data ? (settings.data.enabled ? '已啟用' : '已停用') : '讀取中'}
        </span>
        {run && (
          <span className="muted">
            最近一次自動更新：{statuses[run.status] ?? run.status} · {formatTaipeiTime(run.startedAt)}
          </span>
        )}
        {manualAt && <span className="muted">最近一次手動評估：{formatTaipeiTime(manualAt)}</span>}
      </summary>
      <p className="muted">台灣交易日 18:00 更新觀察清單，再評估所選戰法。</p>
      {settings.isError && (
        <p role="alert" className="error-text">
          排程設定讀取失敗，請重新整理。
        </p>
      )}
      {value && (
        <>
          <fieldset disabled={save.isPending || !rules}>
            <legend>自動排程設定</legend>
            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={value.enabled}
                onChange={(e) => change({ ...value, enabled: e.target.checked })}
              />
              啟用每日排程
            </label>
            <div className="rule-selection">
              {rules
                ?.filter((r) => r.isEnabled)
                .map((rule) => (
                  <label className="checkbox-row" key={rule.id}>
                    <input
                      type="checkbox"
                      checked={value.ruleIds.includes(rule.id)}
                      onChange={() =>
                        change({
                          ...value,
                          ruleIds: value.ruleIds.includes(rule.id)
                            ? value.ruleIds.filter((id) => id !== rule.id)
                            : [...value.ruleIds, rule.id],
                        })
                      }
                    />
                    {rule.name}
                  </label>
                ))}
            </div>
            {rules &&
              value.ruleIds.some((id) => !rules.some((r) => r.id === id && r.isEnabled)) && (
                <p className="muted">部分已選戰法已停用或刪除，下次執行會略過；儲存時將移除。</p>
              )}
          </fieldset>
          <p className="muted">
            未選戰法時只更新最近一年行情。儲存後於下次排程生效；排程完成後以 Telegram
            發送出場訊號與明日觸價價位。
          </p>
          <button
            className="button-primary"
            disabled={save.isPending || !rules}
            onClick={() =>
              save.mutate({
                ...value,
                ruleIds: value.ruleIds.filter((id) =>
                  rules?.some((r) => r.id === id && r.isEnabled),
                ),
              })
            }
          >
            <FontAwesomeIcon icon={faFloppyDisk} />
            {save.isPending ? '儲存中…' : '儲存設定'}
          </button>
          {draft && <span className="muted"> 尚有未儲存設定</span>}
          {save.isSuccess && !draft && <p role="status">已儲存，供下次排程使用。</p>}
          {save.isError && (
            <p role="alert" className="error-text">
              儲存失敗：{save.error.message}。你的選擇尚未儲存。
            </p>
          )}
        </>
      )}
      <div className="schedule-summary" aria-live="polite">
        <h3>最近一次執行</h3>
        {latest.isLoading && <p>讀取中…</p>}
        {latest.isError && <p className="error-text">執行摘要讀取失敗，請重新整理。</p>}
        {latest.isSuccess && !run && <p className="muted">尚無自動執行紀錄。</p>}
        {run && (
          <>
            <p>
              <strong>{statuses[run.status] ?? run.status}</strong> · {formatTaipeiTime(run.startedAt)}
            </p>
            <p>
              共 {run.total} 檔 · 成功 {run.succeeded} 檔 · 失敗 {run.failed} 檔
              {run.status === 'running'
                ? ` · 待完成 ${run.total - run.succeeded - run.failed} 檔`
                : ''}
            </p>
            {run.errors.length > 0 && (
              <details open>
                <summary>本次錯誤（原有有效評估會保留，並標示過期）</summary>
                <ul>
                  {run.errors.map((error) => (
                    <li key={error.id}>
                      <strong>{error.ticker ?? '整批排程'}</strong>：{error.reason}
                    </li>
                  ))}
                </ul>
              </details>
            )}
            <p className="muted">
              成功表示行情更新及所選評估完成，不代表通過戰法。重新整理可查看最新進度。
            </p>
          </>
        )}
      </div>
    </details>
  )
}
