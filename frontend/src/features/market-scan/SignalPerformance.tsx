import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { apiClient } from '../../api/client'
import type { Page } from './types'

interface Group {
  ruleId: number; ruleName: string; horizon: number
  sampleCount: number; sampleInsufficient: boolean; pending: number; unavailable: number
  winRate: number | null; averageNetReturn: number | null; medianNetReturn: number | null
  averageExcessReturn: number | null; positiveExcessRate: number | null
  averageMaxAdverseReturn: number | null
}
interface Observation {
  horizon: number; status: string; reason: string | null
  entryDate: string | null; entryPrice: number | null; dueDate: string | null
  valuationDate: string | null; exitPrice: number | null
  grossReturn: number | null; netReturn: number | null; benchmarkReturn: number | null
  excessReturn: number | null; maxAdverseReturn: number | null
}
interface Signal {
  id: number; signalDate: string; ticker: string; stockName: string; ruleName: string
  olderQuote: boolean; priceDate: string; returns: Observation[]
  costSnapshot: { feeRate: number; feeDiscount: number; taxRateStock: number; taxRateEtf: number }
}
const pct = (v: number | null) => v === null ? '無資料' : `${(v * 100).toFixed(2)}%`
const status: Record<string, string> = { pending: '待計算', completed: '已完成', unavailable: '資料不足' }

export function SignalPerformance({ version }: { version: string }) {
  const [filters, setFilters] = useState({ from: '', to: '', kind: '', minTurnover: '', excludeOlderQuote: false })
  const [selected, setSelected] = useState<number | null>(null)
  const [page, setPage] = useState(1)
  const [ticker, setTicker] = useState('')
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(filters)) {
    if (value !== '' && value !== false) params.set(key, String(value))
  }
  const summary = useQuery({
    queryKey: ['market-signal-performance', filters, version],
    queryFn: () => apiClient.get<{ deployedOn: string | null; groups: Group[] }>(`/market-scan/signal-performance?${params}`),
  })
  const detailParams = new URLSearchParams(params)
  if (selected !== null) detailParams.set('ruleId', String(selected))
  if (ticker) detailParams.set('ticker', ticker)
  detailParams.set('page', String(page))
  const details = useQuery({
    queryKey: ['market-signals', selected, filters, ticker, page, version],
    enabled: selected !== null,
    queryFn: () => apiClient.get<Page<Signal>>(`/market-scan/signals?${detailParams}`),
  })
  const groups = summary.data?.groups ?? []
  const rules = [...new Map(groups.map(g => [g.ruleId, g.ruleName])).entries()]
  const horizons = [...new Set(groups.map(g => g.horizon))].sort((a, b) => a - b)
  const change = (key: string, value: string | boolean) => {
    setFilters(f => ({ ...f, [key]: value })); setPage(1)
  }
  return <section className="card">
    <div className="market-section-heading">
      <h2>戰法績效追蹤</h2>
      <button onClick={() => { void summary.refetch(); if (selected !== null) void details.refetch() }}>重新整理績效</button>
    </div>
    <p className="muted">全市場掃描只列入進場事件：今天符合且前一個有效交易日不符合。</p>
    <p className="muted">記錄自 {summary.data?.deployedOn ?? '階段四 B 部署日'} 起實際掃描的正常命中訊號，不回填部署前的訊號。
      樣本少於 30 筆時不足以作為判斷依據；不同進場事件的持有期間仍可能重疊，並非獨立交易。</p>
    <p className="muted">訊號後下一有效交易日開盤進場，觀察期 1 為進場隔一個交易日收盤；淨報酬包含成本，0050 為毛報酬。
      每次掃描發佈後回填，尚未到期不顯示報酬。還原價未處理分割／減資。</p>
    <div className="filter-bar">
      <label className="field">訊號起日<input type="date" value={filters.from} onChange={e => change('from', e.target.value)} /></label>
      <label className="field">訊號迄日<input type="date" value={filters.to} onChange={e => change('to', e.target.value)} /></label>
      <label className="field">種類<select value={filters.kind} onChange={e => change('kind', e.target.value)}>
        <option value="">全部</option><option value="stock">普通股</option><option value="etf">ETF</option>
      </select></label>
      <label className="field">最低成交金額（元）<input type="number" min="0" value={filters.minTurnover} onChange={e => change('minTurnover', e.target.value)} /></label>
      <label className="checkbox-row"><input type="checkbox" checked={filters.excludeOlderQuote} onChange={e => change('excludeOlderQuote', e.target.checked)} />排除較舊行情</label>
    </div>
    {summary.isLoading && <p>讀取績效…</p>}
    {summary.isError && <p className="error-text" role="alert">{summary.error.message}</p>}
    {groups.length > 0 ? <div className="table-scroll"><table className="data-table">
      <thead><tr><th>戰法</th>{horizons.map(h => <th key={h}>{h} 個交易日</th>)}</tr></thead>
      <tbody>{rules.map(([id, name]) => <tr key={id}>
        <td><button aria-expanded={selected === id} onClick={() => { setSelected(selected === id ? null : id); setPage(1) }}>{name}</button></td>
        {horizons.map(h => {
          const g = groups.find(g => g.ruleId === id && g.horizon === h)
          return <td key={h}>{g ? <>
            <strong>平均淨報酬 {pct(g.averageNetReturn)}</strong>
            <small>{g.sampleCount} 筆 · {g.sampleInsufficient ? '樣本不足' : '已累積 30 筆以上'}</small>
            <small>勝率 {pct(g.winRate)} · 中位數 {pct(g.medianNetReturn)}</small>
            <small>平均超額 {pct(g.averageExcessReturn)} · 超額為正 {pct(g.positiveExcessRate)}</small>
            <small>平均最大不利幅度 {pct(g.averageMaxAdverseReturn)}</small>
            <small>待計算 {g.pending} · 資料不足 {g.unavailable}</small>
          </> : '無資料'}</td>
        })}
      </tr>)}</tbody>
    </table></div> : !summary.isLoading && !summary.isError && <p>尚無符合篩選的訊號。完成掃描後，正常命中才會開始累積。</p>}
    {selected !== null && <div>
      <h3>{rules.find(([id]) => id === selected)?.[1] ?? '戰法'} · 訊號明細</h3>
      <label className="field">股票代號<input value={ticker} maxLength={10} onChange={e => { setTicker(e.target.value); setPage(1) }} /></label>
      {details.isLoading && <p>讀取明細…</p>}
      {details.isError && <p className="error-text" role="alert">{details.error.message}</p>}
      <div className="table-scroll"><table className="data-table">
        <thead><tr><th>訊號／股票</th><th>觀察期</th><th>進場／估值</th><th>淨／毛報酬</th><th>0050／超額</th><th>最大不利幅度／狀態</th></tr></thead>
        <tbody>{details.data?.items.flatMap(s => s.returns.map(r => <tr key={`${s.id}-${r.horizon}`}>
          <td>{s.signalDate}<small>{s.ticker} {s.stockName}</small>{s.olderQuote && <small>較舊行情：{s.priceDate}</small>}
            <details><summary>成本快照</summary><small>買賣各 {(s.costSnapshot.feeRate * 100).toFixed(4)}% × {s.costSnapshot.feeDiscount}；
              股票稅 {pct(s.costSnapshot.taxRateStock)}／ETF 稅 {pct(s.costSnapshot.taxRateEtf)}</small></details></td>
          <td>{r.horizon} 日</td>
          <td>{r.entryDate ?? '—'}<small>進場 {r.entryPrice?.toFixed(2) ?? '—'}</small>
            <small>到期 {r.dueDate ?? '—'}</small><small>估值 {r.valuationDate ?? '—'}／{r.exitPrice?.toFixed(2) ?? '—'}</small></td>
          <td>{pct(r.netReturn)}<small>毛 {pct(r.grossReturn)}</small></td>
          <td>{pct(r.benchmarkReturn)}<small>超額 {pct(r.excessReturn)}</small></td>
          <td>{pct(r.maxAdverseReturn)}<small>{status[r.status] ?? r.status}</small>{r.reason && <small>{r.reason}</small>}</td>
        </tr>))}</tbody>
      </table></div>
      {details.data?.total === 0 && <p>沒有符合條件的訊號。</p>}
      <div className="backtest-pager"><button disabled={page === 1} onClick={() => setPage(p => p - 1)}>上一頁</button>
        <span>第 {page} 頁 · 共 {details.data?.total ?? 0} 筆訊號，每頁 50 筆</span>
        <button disabled={!details.data || page * 50 >= details.data.total} onClick={() => setPage(p => p + 1)}>下一頁</button></div>
    </div>}
  </section>
}
