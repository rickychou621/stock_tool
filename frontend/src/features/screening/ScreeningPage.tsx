import { formatDataDate, WEEKLY_DATA_DATE_TITLE } from '../rules/dataDate'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import {
  faBell,
  faBellSlash,
  faCheck,
  faMagnifyingGlassChart,
  faPaperPlane,
} from '@fortawesome/free-solid-svg-icons'
import { formatTaipeiTime } from '../../lib/time'
import { ETF_CATEGORY_LABELS } from '../settings/etfCategories'
import { formatRuleMetrics } from '../rules/ruleMetrics'
import { RuleStateBadge } from '../rules/components/RuleStateBadge'
import { PageHeader } from '../../components/PageHeader'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { apiClient } from '../../api/client'
import { TodayMatchesTable } from './components/TodayMatchesTable'
import { AddToWatchlistButton } from '../watchlist/components/AddToWatchlistButton'
import { useEffect, useState } from 'react'
import { STATE_LABELS, STATE_URGENCY, type RuleStateCode } from '../rules/state'
import type { ScanJob, ScanSummary, TodayMatchItem, NotificationSummary } from './types'

import type { SavedEvaluation, WatchlistItem } from '../watchlist/types'
import { getSyncHint } from './syncHint'

const FILTER_STATES: RuleStateCode[] = ['ENTRY', 'STALE']

export function ScreeningPage() {
  const [selectedStates, setSelectedStates] = useState<RuleStateCode[]>(['ENTRY'])
  const queryClient = useQueryClient()
  const todayMatches = useQuery({
    queryKey: ['alerts', { todayOnly: true }],
    queryFn: () => apiClient.get<TodayMatchItem[]>('/alerts?today_only=true&limit=50'),
  })
  const watchlist = useQuery({
    queryKey: ['watchlist'],
    queryFn: () => apiClient.get<WatchlistItem[]>('/watchlist?limit=500'),
  })
  const saved = useQuery({
    queryKey: ['saved-evaluations'],
    queryFn: () => apiClient.get<SavedEvaluation[]>('/watchlist/evaluations'),
  })
  const watchlistByTicker = new Map(watchlist.data?.map((item) => [item.ticker, item.id]))
  const evaluationsByRule = new Map(saved.data?.map((item) => [
    `${item.itemId}:${item.ruleId}`, item,
  ]))
  const showWatchlist = watchlist.isSuccess && saved.isSuccess
  const snapshot = useQuery<ScanSummary | null>({
    queryKey: ['latest-scan'],
    queryFn: async () => null,
    initialData: null,
    enabled: false,
  })
  const appliedJob = useQuery<string | null>({
    queryKey: ['applied-scan-job'],
    queryFn: async () => null,
    initialData: null,
    enabled: false,
  })
  const scanJob = useQuery({
    queryKey: ['scan-job'],
    queryFn: () => apiClient.get<ScanJob | null>('/screening/run/latest'),
    refetchInterval: (query) => query.state.data?.status === 'running' ? 1000 : false,
  })
  useEffect(() => {
    const job = scanJob.data
    if (job?.status !== 'done' || !job.summary) return
    if (appliedJob.data === job.jobId) return
    queryClient.setQueryData(['latest-scan'], job.summary)
    queryClient.setQueryData(['applied-scan-job'], job.jobId)
    void queryClient.invalidateQueries({ queryKey: ['alerts'] })
  }, [scanJob.data, appliedJob.data, queryClient])
  const scanMutation = useMutation({
    mutationFn: () => apiClient.post<{ jobId: string }>('/screening/run'),
    onMutate: async () => {
      await queryClient.cancelQueries({ queryKey: ['scan-job'] })
      queryClient.setQueryData(['latest-scan'], null)
      notifyMutation.reset()
    },
    onSuccess: ({ jobId }) => {
      queryClient.setQueryData<ScanJob>(['scan-job'], {
        latestMarketDate: null, jobId, status: 'running', done: 0, total: 0, summary: null, error: null,
      })
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['scan-job'] }),
  })
  const notifyMutation = useMutation({
    mutationFn: async (alertIds: number[]) => {
      const result: NotificationSummary = { sentIds: [], skippedIds: [], failedIds: [] }
      for (let offset = 0; offset < alertIds.length; offset += 500) {
        const part = await apiClient.post<NotificationSummary>('/alerts/notify', {
          alertIds: alertIds.slice(offset, offset + 500),
        })
        result.sentIds.push(...part.sentIds)
        result.skippedIds.push(...part.skippedIds)
        result.failedIds.push(...part.failedIds)
        queryClient.setQueryData<ScanSummary | null>(['latest-scan'], (old) =>
          old
            ? {
                ...old,
                matches: old.matches.map((m) =>
                  m.id !== null && (part.sentIds.includes(m.id) || part.skippedIds.includes(m.id))
                    ? { ...m, isNotified: true }
                    : m,
                ),
              }
            : old,
        )
      }
      return result
    },
  })
  const scanning = scanMutation.isPending || scanJob.data?.status === 'running'
  const scan = snapshot.data
  const syncHint = getSyncHint(scan?.baselineDate, scanJob.data?.latestMarketDate, new Date())
  const matches = scan?.matches ?? []
  const pendingMatches = matches.filter(
    (m) => m.id !== null && !m.isNotified && m.state === 'ENTRY',
  )
  const pendingIds = [...new Set(pendingMatches.flatMap((m) => (m.id === null ? [] : [m.id])))]
  const pendingStocks = new Set(pendingMatches.map((m) => m.ticker)).size
  const counts = Object.fromEntries(
    [...FILTER_STATES, 'NEAR_EXIT', 'HOLD'].map((state) => [state, matches.filter((m) => m.state === state).length]),
  )
  const stockCount = (state: RuleStateCode) =>
    new Set(matches.filter((m) => m.state === state).map((m) => m.ticker)).size
  const visibleMatches = matches
    .filter((m) => selectedStates.includes(m.state))
    .sort(
      (a, b) => STATE_URGENCY[a.state] - STATE_URGENCY[b.state] || a.ticker.localeCompare(b.ticker),
    )
  function toggleState(state: RuleStateCode) {
    setSelectedStates((selected) =>
      selected.includes(state)
        ? selected.length > 1
          ? selected.filter((value) => value !== state)
          : selected
        : [...selected, state],
    )
  }
  return (
    <section>
      <PageHeader
        title="今日符合戰法清單"
        description="先查看掃描結果，再把值得追蹤的個股加入觀察清單。"
        eyebrow="發現機會"
      />
      <div className="card">
        <h3>掃描新機會</h3>
        <p className="muted">
          使用已儲存日K，檢查所有已有行情的啟用股票與全部啟用戰法。不限候選池或觀察清單；掃描不更新行情、不發通知。
        </p>
        <button
          className="button-primary"
          type="button"
          onClick={() => scanMutation.mutate()}
          disabled={scanning || notifyMutation.isPending}
        >
          <FontAwesomeIcon icon={faMagnifyingGlassChart} />
          {scanning
            ? `掃描中…${scanJob.data?.total ? ` ${scanJob.data.done}/${scanJob.data.total}` : ''}`
            : '立即掃描'}
        </button>{' '}
        <button
          className="button-notify"
          type="button"
          disabled={!pendingIds.length || scanning || notifyMutation.isPending}
          onClick={() => {
            if (
              pendingStocks > 50 &&
              !window.confirm(`這次會通知 ${pendingStocks} 檔股票，確定要發送嗎？`)
            )
              return
            notifyMutation.mutate(pendingIds)
          }}
        >
          <FontAwesomeIcon icon={faPaperPlane} />
          {notifyMutation.isPending ? '發送中…' : `通知 Telegram（${pendingStocks} 檔）`}
        </button>
        <p className="muted">
          只通知進場訊號；持股的出場由觀察清單每天 18:00 通知。每則訊息最多彙整 50
          筆，今天已通知的戰法不重送。
        </p>
        {scanMutation.isError && (
          <p role="alert" className="error-text">
            {scanMutation.error.message}
          </p>
        )}
        {scanJob.data?.status === 'failed' && (
          <p role="alert" className="error-text">
            掃描失敗：{scanJob.data.error}
          </p>
        )}
        {notifyMutation.isError && (
          <p role="alert" className="error-text">
            通知請求失敗，請重試；已成功記錄的通知會略過。
          </p>
        )}
        {notifyMutation.data && (
          <p role="status">
            已通知 {notifyMutation.data.sentIds.length} 筆、已通知略過{' '}
            {notifyMutation.data.skippedIds.length} 筆、失敗 {notifyMutation.data.failedIds.length}{' '}
            筆。{notifyMutation.data.failedIds.length > 0 && '再次點擊只會處理尚未成功的項目。'}
          </p>
        )}
      </div>
      {scan && (
        <div className="card">
          <h3>本次掃描結果</h3>
          <p className="muted">
            基準日 {scan.baselineDate ?? '—'}・掃描時間 {formatTaipeiTime(scan.finishedAt).replace(/^\d{4}\//, '')}
          </p>
          {syncHint && <p className={syncHint.className}>{syncHint.message}</p>}
          <p className="muted">
            進場定義：今天符合且前一個有效交易日不符合，與全市場掃描相同。差異：本頁只檢查已同步行情的 {scan.stocksScanned} 檔；全市場掃描涵蓋上市櫃全部標的。行情過期的股票本頁列為「行情過期」，不算進場。
          </p>
          <div className="overview-grid">
            <div className="overview-tile">
              <span>已檢查股票</span>
              <strong>
                {scan.stocksScanned}
                <small> 檔</small>
              </strong>
            </div>
            <div className="overview-tile">
              <span>進場訊號</span>
              <strong>
                {stockCount('ENTRY')}
                <small> 檔（{counts.ENTRY} 筆）</small>
              </strong>
            </div>
          </div>
          <p>
            檢查 {scan.stocksScanned} 檔 × {scan.rulesEvaluated} 條戰法，已排除{' '}
            {scan.excluded} 檔{Object.entries(ETF_CATEGORY_LABELS)
              .filter(([key]) => scan.excludedCategories?.includes(key))
              .map(([, label]) => label).join('／')}ETF。
          </p>
          <div className="state-counts" aria-label="掃描結果狀態篩選">
            {FILTER_STATES.map((state) => (
              <button
                key={state}
                type="button"
                aria-pressed={selectedStates.includes(state)}
                onClick={() => toggleState(state)}
              >
                {state === 'STALE' ? '行情過期' : STATE_LABELS[state]} {counts[state]} 筆（{stockCount(state)} 檔）
              </button>
            ))}
            <select
              aria-label="其他狀態"
              value={selectedStates.find((state) => state === 'NEAR_EXIT' || state === 'HOLD') ?? ''}
              onChange={(event) => setSelectedStates(event.target.value ? [event.target.value as RuleStateCode] : ['ENTRY'])}
            >
              <option value="">其他狀態</option>
              <option value="NEAR_EXIT">接近出場 {counts.NEAR_EXIT} 筆</option>
              <option value="HOLD">續抱 {counts.HOLD} 筆</option>
            </select>
          </div>
          <p className="muted"><small>篩選數字依戰法計算（筆），同一檔可重複</small></p>
          {visibleMatches.length === 0 ? (
            <p>{matches.length === 0 ? '本次沒有符合戰法的股票。' : '所選狀態沒有符合的股票。'}</p>
          ) : (
            <div
              className="table-scroll"
              role="region"
              aria-label="資料表，可左右捲動"
              tabIndex={0}
            >
              <table className="data-table">
                <thead>
                  <tr>
                    <th>股票</th>
                    <th>符合戰法／原因</th>
                    <th>行情日期／價位</th>
                    <th>通知</th>
                    <th>觀察</th>
                  </tr>
                </thead>
                <tbody>
                  {visibleMatches.map((item, index) => {
                    const watchId = watchlistByTicker.get(item.ticker)
                    const evaluation = evaluationsByRule.get(`${watchId}:${item.ruleId}`)
                    const watchState = evaluation?.result.state?.state
                    const differs = watchState && watchState !== item.state
                    return (
                    <tr key={item.id ?? `${item.ticker}-${item.ruleName}-${item.state}-${index}`}>
                      <td>
                        <Link to={`/chart?ticker=${item.ticker}`} state={{ from: '/matches' }}>
                          {item.ticker} {item.name}
                        </Link>
                      </td>
                      <td>
                        {item.state ? (
                          <RuleStateBadge
                            ruleName={item.ruleName}
                            state={item.state}
                            label={item.state === 'STALE' ? '行情過期' : undefined}
                          />
                        ) : (
                          item.ruleName
                        )}
                        {item.largeStopDistance && <span className="status-badge status-warning">停損距離大</span>}
                        {showWatchlist && watchId !== undefined && (
                          <p
                            className={differs ? 'status-warning' : 'muted'}
                            title={differs
                              ? `兩頁使用的行情日期不同：今日清單 ${item.dataDate}，觀察清單 ${evaluation?.result.dataDate}`
                              : undefined}
                          >
                            <small>{evaluation && watchState
                              ? `觀察清單：${STATE_LABELS[watchState]}（${formatDataDate(evaluation.result.dataDate, evaluation.evaluationFrequency, 'MM/DD')}）`
                              : '觀察清單：尚未評估'}</small>
                          </p>
                        )}
                        <p className="muted">
                          <small>{item.reason}</small>
                        </p>
                        {formatRuleMetrics(item).length > 0 && (
                          <p className="muted">{formatRuleMetrics(item).join('｜')}</p>
                        )}
                        <details>
                          <summary>符合原因</summary>
                          <ul>
                            {item.reasons.map((reason, i) => (
                              <li key={i}>{reason}</li>
                            ))}
                          </ul>
                        </details>
                      </td>
                      <td>
                        <span
                          title={item.evaluationFrequency === 'weekly' ? WEEKLY_DATA_DATE_TITLE : undefined}
                        >
                          {formatDataDate(item.dataDate, item.evaluationFrequency)}
                        </span>
                        <br />
                        {item.priceAtTrigger ?? '—'}
                      </td>
                      <td>
                        <span
                          className={`status-badge ${item.id !== null && item.isNotified ? 'status-matched' : ''}`}
                        >
                          <FontAwesomeIcon icon={item.id === null ? faBellSlash : item.isNotified ? faCheck : faBell} /> {item.id === null ? '不通知' : item.isNotified ? '已通知' : '尚未通知'}
                        </span>
                      </td>
                      <td>
                        <AddToWatchlistButton ticker={item.ticker} />
                      </td>
                    </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
          {scan.issues.length > 0 && (
            <details>
              <summary>資料不足或無法評估：{scan.issues.length} 個股票／戰法組合</summary>
              <ul>
                {scan.issues.map((issue, i) => (
                  <li key={i}>
                    {issue.ticker} · {issue.ruleName}：{issue.reason}
                  </li>
                ))}
              </ul>
            </details>
          )}
        </div>
      )}
      <div className="card">
        <h3>今日觸發歷史（最近 50 則）</h3>
        <p className="muted">保留今天曾經符合的紀錄，可能與本次掃描結果不同。</p>
        {todayMatches.isLoading && <p>讀取中…</p>}
        {todayMatches.isError && <p className="error-text">紀錄讀取失敗，請重新整理。</p>}
        {todayMatches.data && <TodayMatchesTable items={todayMatches.data} />}
      </div>
    </section>
  )
}
