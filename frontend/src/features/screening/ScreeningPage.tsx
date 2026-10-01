import { PageHeader } from '../../components/PageHeader'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { apiClient } from '../../api/client'
import { TodayMatchesTable } from './components/TodayMatchesTable'
import { AddToWatchlistButton } from '../watchlist/components/AddToWatchlistButton'
import { getStockName } from '../../lib/stockDirectory'
import type { ScanSummary, TodayMatchItem, NotificationSummary } from './types'

export function ScreeningPage() {
  const queryClient = useQueryClient()
  const todayMatches = useQuery({
    queryKey: ['alerts', { todayOnly: true }],
    queryFn: () => apiClient.get<TodayMatchItem[]>('/alerts?today_only=true&limit=50'),
  })
  const snapshot = useQuery<ScanSummary | null>({
    queryKey: ['latest-scan'],
    queryFn: async () => null,
    initialData: null,
    enabled: false,
  })
  const scanMutation = useMutation({
    mutationFn: () => apiClient.post<ScanSummary>('/screening/run'),
    onMutate: () => {
      queryClient.setQueryData(['latest-scan'], null)
      notifyMutation.reset()
    },
    onSuccess: (data) => {
      queryClient.setQueryData(['latest-scan'], data)
      return queryClient.invalidateQueries({ queryKey: ['alerts'] })
    },
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
                  part.sentIds.includes(m.id) || part.skippedIds.includes(m.id)
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
  const scan = snapshot.data
  const pendingIds = [...new Set(scan?.matches.filter((m) => !m.isNotified).map((m) => m.id) ?? [])]
  const pendingStocks = new Set(scan?.matches.filter((m) => !m.isNotified).map((m) => m.ticker))
    .size
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
          disabled={scanMutation.isPending || notifyMutation.isPending}
        >
          {scanMutation.isPending ? '掃描中…' : '立即掃描'}
        </button>{' '}
        <button
          className="button-notify"
          type="button"
          disabled={!pendingIds.length || scanMutation.isPending || notifyMutation.isPending}
          onClick={() => notifyMutation.mutate(pendingIds)}
        >
          {notifyMutation.isPending ? '發送中…' : `通知 Telegram（${pendingStocks} 檔）`}
        </button>
        <p className="muted">
          只通知本次符合戰法的個股；同股符合多條戰法會分別通知，今天已通知的戰法不重送。
        </p>
        {scanMutation.isError && (
          <p role="alert" className="error-text">
            掃描失敗，請重試。
          </p>
        )}
        {notifyMutation.isError && (
          <p role="alert" className="error-text">
            通知請求失敗，請重試；已成功記錄的通知會略過。
          </p>
        )}
        {notifyMutation.data && (
          <p role="status">
            已發送 {notifyMutation.data.sentIds.length} 則、已通知略過{' '}
            {notifyMutation.data.skippedIds.length} 則、失敗 {notifyMutation.data.failedIds.length}{' '}
            則。{notifyMutation.data.failedIds.length > 0 && '再次點擊只會處理尚未成功的項目。'}
          </p>
        )}
      </div>
      {scan && (
        <div className="card">
          <h3>本次掃描結果</h3>
          <div className="overview-grid">
            <div className="overview-tile">
              <span>已檢查股票</span>
              <strong>
                {scan.stocksScanned}
                <small> 檔</small>
              </strong>
            </div>
            <div className="overview-tile">
              <span>使用戰法</span>
              <strong>
                {scan.rulesEvaluated}
                <small> 條</small>
              </strong>
            </div>
            <div className="overview-tile">
              <span>符合戰法</span>
              <strong>
                {new Set(scan.matches.map((m) => m.ticker)).size}
                <small> 檔</small>
              </strong>
            </div>
          </div>
          <p>
            檢查 {scan.stocksScanned} 檔 × {scan.rulesEvaluated} 條戰法，
            {new Set(scan.matches.map((m) => m.ticker)).size} 檔符合，新增 {scan.newAlerts} 則紀錄。
          </p>
          {scan.matches.length === 0 ? (
            <p>本次沒有符合戰法的股票。</p>
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
                  {scan.matches.map((item) => (
                    <tr key={item.id}>
                      <td>
                        <Link to={`/chart?ticker=${item.ticker}`} state={{ from: '/matches' }}>
                          {item.ticker} {getStockName(item.ticker)}
                        </Link>
                      </td>
                      <td>
                        {item.ruleName}
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
                        {item.dataDate ?? '無資料'}
                        <br />
                        {item.priceAtTrigger ?? '—'}
                      </td>
                      <td>
                        <span className={`status-badge ${item.isNotified ? 'status-matched' : ''}`}>
                          {item.isNotified ? '已通知' : '尚未通知'}
                        </span>
                      </td>
                      <td>
                        <AddToWatchlistButton ticker={item.ticker} />
                      </td>
                    </tr>
                  ))}
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
