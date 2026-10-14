import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../../api/client'
import { PageHeader } from '../../components/PageHeader'
import type { WatchRule } from '../rules/types'
import type { Detail, Metrics, Report, StockPerformance } from './types'

const percent = (n: number | null) => (n === null ? '無資料' : `${(n * 100).toFixed(2)}%`)
const price = (n: number | null) => (n === null ? '—' : n.toFixed(2))
const states: Record<string, string> = {
  running: '執行中',
  succeeded: '完成',
  failed: '失敗',
  partial_failure: '部分成功',
  interrupted: '已中斷',
  first: '首次符合',
  continued: '持續符合',
  invalidated: '失效',
  reentered: '再次符合',
  not_met: '未符合',
}
const statusLabels = { closed: '已完成', open: '持有中', unfilled: '未成交' }
const metricHeaders = ['交易次數', '勝率', '平均報酬', '複利報酬', '最大回撤', '獲利因子']
function MetricCells({ metrics: m }: { metrics: Metrics }) {
  return (
    <>
      <td>
        {m.tradeCount}
        {m.insufficientSample && <small className="backtest-warning">樣本不足</small>}
      </td>
      <td>{percent(m.winRate)}</td>
      <td>{percent(m.averageReturn)}</td>
      <td>{percent(m.compoundReturn)}</td>
      <td>{percent(m.maxDrawdown)}</td>
      <td>{!m.tradeCount ? '無資料' : m.noLosses ? '無虧損' : m.profitFactor?.toFixed(2)}</td>
    </>
  )
}
function TradeDetails({ stock, batch }: { stock: StockPerformance; batch: string }) {
  const [offset, setOffset] = useState(0)
  const detail = useQuery({
    queryKey: ['backtest-detail', stock.id, stock.calculatedAt, batch, offset],
    queryFn: () =>
      apiClient.get<Detail>(
        `/backtests/results/${stock.id}?offset=${offset}&limit=50&expectedBatchId=${stock.batchId}`,
      ),
  })
  const data = detail.data
  return (
    <div className="card">
      <h2>
        {stock.ticker} {stock.stockName} · {stock.ruleName}
      </h2>
      {stock.stale && <p className="backtest-warning">以下為上次成功結果，已過期。</p>}
      {detail.isLoading && <p>讀取明細…</p>}
      {detail.isError && (
        <p role="alert" className="error-text">
          明細讀取失敗，請重新整理。
        </p>
      )}
      {data && (
        <>
          <p className="muted">
            成交價格統一還原至 {data.priceBasisDate}；共 {data.tradeTotal} 筆交易紀錄。
          </p>
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  {[
                    '狀態',
                    '買進訊號',
                    '買進日期／價格',
                    '賣出訊號',
                    '賣出日期／價格',
                    '持有交易日',
                    '已實現報酬',
                    '未實現報酬',
                  ].map((h) => (
                    <th key={h}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.trades.map((t, i) => (
                  <tr key={i}>
                    <td>
                      {statusLabels[t.status]}
                      {t.pendingSide === 'sell' && <small>賣出未成交</small>}
                    </td>
                    <td>{t.entrySignalDate}</td>
                    <td>
                      {t.entryDate ?? '—'}
                      <br />
                      {price(t.entryPrice)}
                    </td>
                    <td>{t.exitSignalDate ?? '—'}</td>
                    <td>
                      {t.exitDate ?? '—'}
                      <br />
                      {price(t.exitPrice)}
                    </td>
                    <td>{t.holdingDays ?? '—'}</td>
                    <td>{percent(t.returnRate)}</td>
                    <td>
                      {percent(t.unrealizedReturn)}
                      {t.valuationDate && <small>估值日 {t.valuationDate}</small>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {!data.tradeTotal && <p>本次沒有產生交易。</p>}
          <details>
            <summary>逐日訊號狀態（共 {data.signalTotal} 筆）</summary>
            <div className="backtest-signals">
              {data.signals.map((s) => (
                <p key={s.date}>
                  {s.date} · {states[s.state]}
                </p>
              ))}
            </div>
          </details>
          <div className="backtest-pager">
            <button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 50))}>
              上一頁
            </button>
            <span>第 {Math.floor(offset / 50) + 1} 頁 · 交易與訊號每頁各 50 筆</span>
            <button
              disabled={offset + 50 >= Math.max(data.tradeTotal, data.signalTotal)}
              onClick={() => setOffset(offset + 50)}
            >
              下一頁
            </button>
          </div>
        </>
      )}
    </div>
  )
}

export function BacktestPage() {
  const client = useQueryClient()
  const [chosen, setChosen] = useState<number[] | null>(null)
  const [ticker, setTicker] = useState('all')
  const [ruleFilter, setRuleFilter] = useState('all')
  const [sort, setSort] = useState<'winRate' | 'tradeCount' | 'averageReturn'>('winRate')
  const [selected, setSelected] = useState<number | null>(null)
  const rules = useQuery({
    queryKey: ['rules'],
    queryFn: () => apiClient.get<WatchRule[]>('/rules?limit=50'),
  })
  const report = useQuery({
    queryKey: ['backtest-report'],
    queryFn: () => apiClient.get<Report>('/backtests/latest'),
    refetchInterval: (query) => (query.state.data?.task?.status === 'running' ? 3000 : false),
  })
  const running = report.data?.task?.status === 'running'
  const start = useMutation({
    mutationFn: (ruleIds: number[]) => apiClient.post('/backtests', { ruleIds }),
    onSuccess: async () => {
      setSelected(null)
      await client.invalidateQueries({ queryKey: ['backtest-report'] })
    },
    onError: async () => {
      await client.invalidateQueries({ queryKey: ['backtest-report'] })
    },
  })
  const active = (rules.data ?? []).filter((r) => r.isEnabled)
  const ids = (chosen ?? active.map((r) => r.id)).filter((id) => active.some((r) => r.id === id))
  const task = report.data?.task
  const stocks = report.data?.stocks ?? []
  const visible = stocks
    .filter(
      (s) =>
        (ticker === 'all' || s.ticker === ticker) &&
        (ruleFilter === 'all' || s.ruleId === Number(ruleFilter)),
    )
    .sort(
      (a, b) =>
        (b.metrics[sort] ?? -Infinity) - (a.metrics[sort] ?? -Infinity) ||
        a.ticker.localeCompare(b.ticker),
    )
  const detailStock = visible.find((s) => s.id === selected)
  return (
    <section className="backtest-page">
      <PageHeader title="戰法回測" description="以最近三年的歷史訊號與模擬交易，檢視戰法表現。" />
      <div className="card">
        <fieldset disabled={running || start.isPending}>
          <legend>回測戰法</legend>
          <div className="rule-selection">
            {active.map((r) => (
              <label className="checkbox-row" key={r.id}>
                <input
                  type="checkbox"
                  checked={ids.includes(r.id)}
                  onChange={() =>
                    setChosen(ids.includes(r.id) ? ids.filter((id) => id !== r.id) : [...ids, r.id])
                  }
                />
                {r.name}
              </label>
            ))}
          </div>
        </fieldset>
        {rules.isError && <p className="error-text">戰法讀取失敗。</p>}
        <p className="muted">範圍為目前觀察清單；與每日排程設定分開。關閉頁面仍會繼續執行。</p>
        <button
          className="button-primary"
          disabled={!ids.length || running || start.isPending || report.isLoading || report.isError}
          onClick={() => start.mutate(ids)}
        >
          {running || start.isPending ? '回測執行中…' : '執行回測'}
        </button>
        {start.isError && (
          <p role="alert" className="error-text">
            {start.error.message}
          </p>
        )}
        {task && (
          <div className="schedule-summary" role="status">
            <strong>{states[task.status]}</strong> · 已完成 {task.completed}／{task.total} 檔
            <p>
              成功 {task.succeeded} 檔 · 失敗 {task.failed} 檔 · 期間 {task.startDate}～
              {task.endDate}
            </p>
            {running && (
              <p className="muted">
                正在準備歷史資料或計算，每 3 秒更新進度；首次補齊多年資料可能較久。
              </p>
            )}
            {task.errors.length > 0 && (
              <details open>
                <summary>錯誤資訊</summary>
                <ul>
                  {task.errors.map((e, i) => (
                    <li key={i}>
                      {e.ticker ?? '整批任務'}：{e.reason}
                    </li>
                  ))}
                </ul>
              </details>
            )}
          </div>
        )}
        {report.isError && (
          <p role="alert" className="error-text">
            回測資料讀取失敗，請重新整理。
          </p>
        )}
        {report.isSuccess && !task && <p className="muted">尚無回測結果，勾選戰法後即可開始。</p>}
      </div>
      <div className="card backtest-notes">
        <p>訊號後下一有效交易日開盤成交；不計交易成本、滑價，也不額外將股利再投入。</p>
        <p>
          複利報酬與最大回撤僅依已完成交易計算，不含持倉期間浮動損益。跨股票複利僅供比較，不是實際投資組合績效。
        </p>
        <p>少於 10 筆已完成交易標示樣本不足；上市較晚或需較長指標暖機的股票，實際期間可能較短。</p>
      </div>
      {task && (
        <>
          <div className="card">
            <h2>戰法整體績效</h2>
            <p className="muted">
              僅統計本次成功股票；期間顯示最早至最晚日期，各股涵蓋長度可能不同。
            </p>
            <div className="table-scroll">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>戰法／股票數</th>
                    <th>實際期間</th>
                    {metricHeaders.map((h) => (
                      <th key={h}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {report.data?.overall.map((r) => (
                    <tr key={r.ruleId}>
                      <td>
                        {r.ruleName}
                        <small>{r.stockCount} 檔</small>
                      </td>
                      <td>
                        {r.actualStart}
                        <br />
                        {r.actualEnd}
                      </td>
                      <MetricCells metrics={r.metrics} />
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {!report.data?.overall.length && <p>本次尚無成功回測股票，不混入舊結果。</p>}
          </div>
          <div className="card">
            <h2>個股績效</h2>
            <div className="filter-bar">
              <label className="field">
                股票
                <select
                  aria-label="回測股票篩選"
                  value={ticker}
                  onChange={(e) => {
                    setTicker(e.target.value)
                    setSelected(null)
                  }}
                >
                  <option value="all">全部股票</option>
                  {[...new Map(stocks.map((s) => [s.ticker, s.stockName])).entries()].map(
                    ([t, n]) => (
                      <option key={t} value={t}>
                        {t} {n}
                      </option>
                    ),
                  )}
                </select>
              </label>
              <label className="field">
                戰法
                <select
                  aria-label="回測戰法篩選"
                  value={ruleFilter}
                  onChange={(e) => {
                    setRuleFilter(e.target.value)
                    setSelected(null)
                  }}
                >
                  <option value="all">全部戰法</option>
                  {[...new Map(stocks.map((s) => [s.ruleId, s.ruleName])).entries()].map(
                    ([id, n]) => (
                      <option key={id} value={id}>
                        {n}
                      </option>
                    ),
                  )}
                </select>
              </label>
              <label className="field">
                排序
                <select
                  aria-label="回測排序"
                  value={sort}
                  onChange={(e) => setSort(e.target.value as typeof sort)}
                >
                  <option value="winRate">勝率由高到低</option>
                  <option value="tradeCount">交易次數由多到少</option>
                  <option value="averageReturn">平均報酬由高到低</option>
                </select>
              </label>
            </div>
            <div className="table-scroll">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>股票／戰法</th>
                    <th>實際期間</th>
                    {metricHeaders.map((h) => (
                      <th key={h}>{h}</th>
                    ))}
                    <th>持有／未成交</th>
                    <th>明細</th>
                  </tr>
                </thead>
                <tbody>
                  {visible.map((s) => (
                    <tr key={s.id}>
                      <td>
                        {s.ticker} {s.stockName}
                        <small>{s.ruleName}</small>
                        {s.stale && (
                          <strong className="backtest-warning">過期：上次成功結果</strong>
                        )}
                      </td>
                      <td>
                        {s.actualStart}
                        <br />
                        {s.actualEnd}
                        <small>略過 {s.skippedSessions} 個無有效行情日</small>
                      </td>
                      <MetricCells metrics={s.metrics} />
                      <td>
                        {s.openCount}／{s.unfilledCount}
                      </td>
                      <td>
                        <button onClick={() => setSelected(s.id)}>查看明細</button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {!visible.length && <p>沒有符合篩選條件的結果。</p>}
          </div>
          {detailStock && (
            <TradeDetails
              key={`${detailStock.id}-${detailStock.calculatedAt}`}
              stock={detailStock}
              batch={task.batchId}
            />
          )}
        </>
      )}
    </section>
  )
}
