import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../../api/client'
import { PageHeader } from '../../components/PageHeader'
import { SignalPerformance } from './SignalPerformance'
import type { WatchRule } from '../rules/types'
import type { Candidate, Page, ScanError, ScanSettings, Summary, Task, Tasks } from './types'

const labels: Record<string, string> = {
  pending: '等待中',
  running: '執行中',
  completed: '完成',
  partial_completed: '部分完成',
  failed: '失敗',
  skipped: '已略過',
  interrupted: '已中斷',
  normal: '正常',
  stale: '過期',
  insufficient_history: '歷史不足',
}
const when = (s: string | null) =>
  s ? new Date(s).toLocaleString('zh-TW', { timeZone: 'Asia/Taipei', hour12: false }) : '—'
const number = (n: number | null) =>
  n === null ? '無資料' : n.toLocaleString('zh-TW', { maximumFractionDigits: 2 })
const active = (task: Task | null | undefined) =>
  task?.status === 'running' || task?.status === 'pending'
const metricLabel = (key: string) => {
  const names: Record<string, string> = {
    'bollinger_mid_up.mid': '布林中軌',
    'bollinger_mid_up.upper': '布林上軌',
    'bollinger_mid_up.slope': '中軌變化',
    'kd_golden_cross.k': '月 K',
    'kd_golden_cross.d': '月 D',
    'macd_positive.dif': '月 DIF',
    'macd_positive.signal': '月 MACD 訊號',
    'macd_positive.histogram': '月 MACD 柱',
    'macd_histogram_rising.histogram': '本月柱狀體',
    'macd_histogram_rising.previous': '上月柱狀體',
    'ema_golden_cross.short': '短 EMA',
    'ema_golden_cross.long': '長 EMA',
    'volume_spike.ratio': '量比',
    'volume_spike.average': '均量',
  }
  return names[key] ?? key
}
function RuleChoices({
  rules,
  selected,
  onChange,
  label,
}: {
  rules: WatchRule[]
  selected: number[]
  onChange: (ids: number[]) => void
  label: string
}) {
  return (
    <fieldset className="market-rules">
      <legend>{label}</legend>
      {rules.map((rule) => (
        <label className="checkbox-row" key={rule.id}>
          <input
            type="checkbox"
            checked={selected.includes(rule.id)}
            onChange={(e) =>
              onChange(
                e.target.checked ? [...selected, rule.id] : selected.filter((id) => id !== rule.id),
              )
            }
          />
          {rule.name}
        </label>
      ))}
    </fieldset>
  )
}
function Progress({ task }: { task: Task | null | undefined }) {
  if (!task) return <p className="muted">尚未執行</p>
  return (
    <div className="market-progress" aria-live="polite">
      <p>
        <strong>{labels[task.status] ?? task.status}</strong> · {task.processed} / {task.total} 檔
      </p>
      {active(task) && <progress value={task.processed} max={task.total || 1} />}
      <p>
        成功 {task.succeeded} · 失敗 {task.failed} · 歷史不足 {task.insufficient}
      </p>
      <small>
        開始 {when(task.startedAt)}
        {task.finishedAt && ` · 結束 ${when(task.finishedAt)}`}
      </small>
      {task.warnings.map((warning, i) => (
        <p key={i} className="backtest-warning">
          {warning}
        </p>
      ))}
    </div>
  )
}
function Errors({ kind, version }: { kind: string; version: string }) {
  const [page, setPage] = useState(1)
  const query = useQuery({
    queryKey: ['market-errors', kind, page, version],
    queryFn: () => apiClient.get<Page<ScanError>>(`/market-scan/errors?kind=${kind}&page=${page}`),
  })
  return (
    <details className="market-errors">
      <summary>
        查看{kind === 'scan' ? '掃描' : '初始化'}錯誤（{query.data?.total ?? 0}）
      </summary>
      {query.isError && <p role="alert">錯誤紀錄讀取失敗</p>}
      {query.data?.items.map((item, i) => (
        <p key={i}>
          <strong>
            {item.ticker ?? '整體任務'} {item.ruleId && `· 戰法 ${item.ruleId}`}
          </strong>
          ：{item.reason}
        </p>
      ))}
      {((query.data?.total ?? 0) > 50 || page > 1) && (
        <div className="market-pagination">
          <button disabled={page === 1} onClick={() => setPage((p) => p - 1)}>
            上一頁錯誤
          </button>
          <span>第 {page} 頁</span>
          <button
            disabled={page * 50 >= (query.data?.total ?? 0)}
            onClick={() => setPage((p) => p + 1)}
          >
            下一頁錯誤
          </button>
        </div>
      )}
    </details>
  )
}
const initialFilters: Record<string, string> = {
  search: '',
  kind: '',
  ruleId: '',
  priceDate: '',
  minPrice: '',
  maxPrice: '',
  minVolume: '',
  minTurnover: '',
  indicator: '',
  indicatorMin: '',
  indicatorMax: '',
  status: 'normal',
  sort: 'ticker',
  direction: 'asc',
}
export function MarketScanPage() {
  const client = useQueryClient()
  const settings = useQuery({
    queryKey: ['market-settings'],
    queryFn: () => apiClient.get<ScanSettings>('/market-scan/settings'),
  })
  const rules = useQuery({
    queryKey: ['rules'],
    queryFn: () => apiClient.get<WatchRule[]>('/rules'),
  })
  const tasks = useQuery({
    queryKey: ['market-tasks'],
    queryFn: () => apiClient.get<Tasks>('/market-scan/tasks'),
    refetchInterval: (q) =>
      active(q.state.data?.scan) || active(q.state.data?.initialize) ? 3000 : false,
  })
  const summary = useQuery({
    queryKey: ['market-summary'],
    queryFn: () => apiClient.get<Summary | null>('/market-scan/summary'),
  })
  const indicators = useQuery({
    queryKey: ['market-indicators'],
    queryFn: () => apiClient.get<string[]>('/market-scan/indicators'),
  })
  const [draft, setDraft] = useState<{ enabled: boolean; ruleIds: number[] } | null>(null)
  const [manual, setManual] = useState<number[] | null>(null)
  const [filters, setFilters] = useState(initialFilters)
  const [page, setPage] = useState(1)
  const selected = manual ?? settings.data?.ruleIds ?? []
  const automatic = draft ?? settings.data ?? { enabled: true, ruleIds: [] }
  const available = rules.data?.filter((r) => r.isEnabled) ?? []
  const params = new URLSearchParams(Object.entries(filters).filter(([, v]) => v !== ''))
  params.set('page', String(page))
  const candidates = useQuery({
    queryKey: ['market-candidates', filters, page],
    queryFn: () => apiClient.get<Page<Candidate>>(`/market-scan/candidates?${params}`),
  })
  const finishVersion = [
    tasks.data?.scan?.batchId,
    tasks.data?.scan?.status,
    tasks.data?.initialize?.batchId,
    tasks.data?.initialize?.status,
  ].join(':')
  const previousVersion = useRef('')
  useEffect(() => {
    if (previousVersion.current !== finishVersion) {
      previousVersion.current = finishVersion
      void client.invalidateQueries({ queryKey: ['market-summary'] })
      void client.invalidateQueries({ queryKey: ['market-candidates'] })
      void client.invalidateQueries({ queryKey: ['market-indicators'] })
    }
  }, [client, finishVersion])
  const save = useMutation({
    mutationFn: () => apiClient.put<ScanSettings>('/market-scan/settings', automatic),
    onSuccess: (data) => {
      client.setQueryData(['market-settings'], data)
      setDraft(null)
    },
  })
  const start = useMutation({
    mutationFn: (kind: 'run' | 'initialize' | 'dividends') =>
      apiClient.post(`/market-scan/${kind === 'dividends' ? 'initialize' : kind}`, {
        ruleIds: selected, ...(kind === 'run' ? {} : { mode: kind === 'dividends' ? 'dividends' : 'prices' }),
      }),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: ['market-tasks'] })
    },
  })
  const busy = active(tasks.data?.scan) || active(tasks.data?.initialize) || start.isPending
  const refresh = () => {
    for (const key of [
      'market-settings',
      'market-tasks',
      'market-summary',
      'market-candidates',
      'market-indicators',
      'market-errors',
      'market-signal-performance',
      'market-signals',
    ])
      void client.invalidateQueries({ queryKey: [key] })
  }
  const filter = (key: string, value: string) => {
    setFilters((f) => ({ ...f, [key]: value }))
    setPage(1)
  }
  return (
    <div className="page-stack market-scan-page">
      <PageHeader
        title="全市場掃描"
        description="從上市普通股與 ETF 發掘符合戰法的標的。先備妥歷史行情，再查看最新候選。"
        eyebrow="市場探索"
      />
      <div className="market-controls">
        <section className="card">
          <h2>每日自動掃描</h2>
          <p className="muted">TWSE 交易日 19:00（台北時間）</p>
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={automatic.enabled}
              onChange={(e) => setDraft({ ...automatic, enabled: e.target.checked })}
            />
            啟用每日掃描
          </label>
          <RuleChoices
            rules={available}
            selected={automatic.ruleIds}
            onChange={(ruleIds) => setDraft({ ...automatic, ruleIds })}
            label="自動使用戰法"
          />
          <button
            className="button-primary"
            disabled={!settings.data || save.isPending}
            onClick={() => save.mutate()}
          >
            {save.isPending ? '儲存中…' : '儲存自動設定'}
          </button>
          {!automatic.ruleIds.length && <p className="muted">未選戰法時自動略過，保留既有候選。</p>}
          {save.isSuccess && !draft && <p role="status">自動設定已儲存</p>}
        </section>
        <section className="card">
          <h2>手動全市場掃描</h2>
          <RuleChoices
            rules={available}
            selected={selected}
            onChange={setManual}
            label="本次使用戰法"
          />
          <p className="muted">
            本次選擇不改動自動設定。掃描完成後更新下方候選並發送 Telegram 完成提示。
          </p>
          <div className="market-actions">
            <button
              className="button-primary"
              disabled={busy || !selected.length || !tasks.data || !settings.data}
              onClick={() => start.mutate('run')}
            >
              開始全市場掃描
            </button>
            <button disabled={!settings.data} onClick={() => setManual(null)}>
              沿用自動設定
            </button>
          </div>
          <Progress task={tasks.data?.scan} />
          <Errors kind="scan" version={`${finishVersion}:${tasks.data?.scan?.processed}`} />
        </section>
      </div>
      <section className="card">
        <div className="market-section-heading">
          <div>
            <h2>歷史行情初始化</h2>
            <p className="muted">
              先下載歷史行情，再自行補齊股利。股利每檔一次查完整所需期間，仍受來源額度限制。
              未確認股利完整的標的會顯示「還原資料未完整」，不列為正常戰法命中。
            </p>
          </div>
          <button
            className="button-add"
            disabled={busy || !selected.length || !tasks.data || !settings.data}
            onClick={() => start.mutate('initialize')}
          >
            下載歷史行情
          </button>
        </div>
        <button className="button-add" disabled={busy || !selected.length || !tasks.data || !settings.data}
          onClick={() => start.mutate('dividends')}>補齊歷史股利</button>
        <Progress task={tasks.data?.initialize} />
        <Errors
          kind="initialize"
          version={`${finishVersion}:${tasks.data?.initialize?.processed}`}
        />
      </section>
      {(settings.isError ||
        rules.isError ||
        tasks.isError ||
        summary.isError ||
        indicators.isError) && (
        <p className="error-text" role="alert">
          部分資料讀取失敗，請重新整理。
        </p>
      )}
      {(save.error || start.error) && (
        <p className="error-text" role="alert">
          {(save.error || start.error)?.message}
        </p>
      )}
      <section className="card">
        <div className="market-section-heading">
          <h2>已發佈候選</h2>
          <button onClick={refresh}>重新整理</button>
        </div>
        {busy && <p className="backtest-warning">任務執行中，以下仍為上一批已發佈結果。</p>}
        <p className="muted">全市場掃描只列入進場事件：今天符合且前一個有效交易日不符合。</p>
        {summary.data ? (
          <>
            <p>
              {summary.data.source === 'automatic' ? '自動' : '手動'}掃描 ·{' '}
              {labels[summary.data.status]} · {when(summary.data.finishedAt)} · 基準日{' '}
              {summary.data.baseline}
            </p>
            <p>延續中 {summary.data.continuing ?? 0} 筆（未列入候選）</p>
            <p>使用戰法：{summary.data.rules.map((r) => r.name).join('、')}</p>
            <div className="market-stats">
              <div>
                <strong>
                  {summary.data.succeeded} / {summary.data.total}
                </strong>
                <span>成功評估標的</span>
              </div>
              <div>
                <strong>{summary.data.normalCount}</strong>
                <span>正常命中列</span>
              </div>
              <div>
                <strong>{summary.data.abnormalCount}</strong>
                <span>異常舊列</span>
              </div>
              <div>
                <strong>
                  {summary.data.failed} / {summary.data.insufficient}
                </strong>
                <span>失敗／歷史不足標的</span>
              </div>
            </div>
            <small className="muted">
              同檔可符合多個戰法；部分戰法失敗或資料不足時，標的計數可能重疊。
            </small>
            {summary.data.warnings.map((w, i) => (
              <p className="backtest-warning" key={i}>
                {w}
              </p>
            ))}
          </>
        ) : (
          <p className="muted">尚無已發佈結果，請先初始化或開始掃描。</p>
        )}
        <div className="market-filters">
          <label className="field">
            代碼／名稱
            <input
              aria-label="代碼或名稱"
              value={filters.search}
              onChange={(e) => filter('search', e.target.value)}
              placeholder="搜尋股票或 ETF"
            />
          </label>
          <label className="field">
            資料狀態
            <select
              aria-label="資料狀態"
              value={filters.status}
              onChange={(e) => filter('status', e.target.value)}
            >
              {[
                ['normal', '正常'],
                ['stale', '過期'],
                ['insufficient_history', '歷史不足'],
                ['all', '全部'],
              ].map(([v, l]) => (
                <option key={v} value={v}>
                  {l}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            種類
            <select
              aria-label="種類"
              value={filters.kind}
              onChange={(e) => filter('kind', e.target.value)}
            >
              <option value="">全部種類</option>
              <option value="stock">普通股</option>
              <option value="etf">ETF</option>
            </select>
          </label>
          <label className="field">
            戰法
            <select
              aria-label="候選戰法"
              value={filters.ruleId}
              onChange={(e) => filter('ruleId', e.target.value)}
            >
              <option value="">全部戰法</option>
              {rules.data?.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.name}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            行情日期
            <input
              type="date"
              value={filters.priceDate}
              onChange={(e) => filter('priceDate', e.target.value)}
            />
          </label>
          {[
            ['minPrice', '最低收盤價'],
            ['maxPrice', '最高收盤價'],
            ['minVolume', '最低成交量（股）'],
            ['minTurnover', '最低成交金額（元）'],
          ].map(([key, label]) => (
            <label className="field" key={key}>
              {label}
              <input
                type="number"
                min="0"
                step="any"
                value={filters[key]}
                onChange={(e) => filter(key, e.target.value)}
                placeholder="不設門檻"
              />
            </label>
          ))}
          <label className="field">
            技術指標
            <select
              aria-label="技術指標"
              value={filters.indicator}
              onChange={(e) => {
                setFilters((f) => ({
                  ...f,
                  indicator: e.target.value,
                  indicatorMin: '',
                  indicatorMax: '',
                  sort: f.sort === 'indicator' && !e.target.value ? 'ticker' : f.sort,
                }))
                setPage(1)
              }}
            >
              <option value="">不篩選</option>
              {indicators.data?.map((key) => (
                <option key={key} value={key}>
                  {metricLabel(key)}
                </option>
              ))}
            </select>
          </label>
          {[
            ['indicatorMin', '指標下限'],
            ['indicatorMax', '指標上限'],
          ].map(([key, label]) => (
            <label className="field" key={key}>
              {label}
              <input
                disabled={!filters.indicator}
                type="number"
                step="any"
                value={filters[key]}
                onChange={(e) => filter(key, e.target.value)}
              />
            </label>
          ))}
          <label className="field">
            排序
            <select
              aria-label="排序"
              value={filters.sort}
              onChange={(e) => filter('sort', e.target.value)}
            >
              {[
                ['ticker', '股票代碼'],
                ['stockName', '股票名稱'],
                ['kind', '種類'],
                ['ruleId', '戰法'],
                ['close', '收盤價'],
                ['priceDate', '行情日期'],
                ['volume', '成交量'],
                ['turnover', '成交金額'],
                ['scannedAt', '掃描時間'],
                ['status', '資料狀態'],
                ...(filters.indicator ? [['indicator', '所選指標']] : []),
              ].map(([v, l]) => (
                <option key={v} value={v}>
                  {l}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            順序
            <select
              aria-label="順序"
              value={filters.direction}
              onChange={(e) => filter('direction', e.target.value)}
            >
              <option value="asc">由小到大</option>
              <option value="desc">由大到小</option>
            </select>
          </label>
          <button
            onClick={() => {
              setFilters(initialFilters)
              setPage(1)
            }}
          >
            清除篩選
          </button>
        </div>
        {candidates.isError && (
          <p role="alert" className="error-text">
            候選查詢失敗，請檢查篩選範圍後重新整理。
          </p>
        )}
        {candidates.isFetching && <p className="muted">讀取候選中…</p>}
        <div className="table-scroll">
          <table className="data-table market-table">
            <thead>
              <tr>
                {[
                  '標的／種類',
                  '符合戰法',
                  '收盤價／行情日',
                  '成交量／金額',
                  '原因與技術指標',
                  '資料狀態／掃描時間',
                ].map((h) => (
                  <th key={h}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {candidates.data?.items.map((row) => (
                <tr key={row.id}>
                  <td>
                    <strong>
                      {row.ticker} {row.stockName}
                    </strong>
                    <small>{row.kind === 'etf' ? 'ETF' : '普通股'}</small>
                  </td>
                  <td>{row.ruleName}</td>
                  <td>
                    {number(row.close)}
                    <small>{row.priceDate}</small>
                    {row.olderQuote && <span className="market-badge is-warning">行情較舊</span>}
                  </td>
                  <td>
                    {number(row.volume)} 股
                    <small>
                      {number(row.turnover)}
                      {row.turnover !== null ? ' 元' : ''}
                    </small>
                  </td>
                  <td>
                    <p>{row.reason}</p>
                    <div className="market-indicators">
                      {Object.entries(row.indicators).map(([key, value]) => (
                        <span key={key}>
                          {metricLabel(key)} {number(value)}
                        </span>
                      ))}
                    </div>
                  </td>
                  <td>
                    <span
                      className={`market-badge ${row.status === 'normal' ? 'is-normal' : 'is-warning'}`}
                    >
                      {labels[row.status]}
                    </span>
                    {row.statusReason && <small>{row.statusReason}</small>}
                    <small>{when(row.scannedAt)}</small>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!candidates.isFetching && !candidates.isError && !candidates.data?.items.length && (
          <p className="muted">目前篩選範圍沒有候選資料。</p>
        )}
        <div className="market-pagination">
          <button disabled={page === 1} onClick={() => setPage((p) => p - 1)}>
            上一頁
          </button>
          <span>
            第 {page} 頁 · 共 {candidates.data?.total ?? 0} 列 · 每頁 50 列
          </span>
          <button
            disabled={page * 50 >= (candidates.data?.total ?? 0)}
            onClick={() => setPage((p) => p + 1)}
          >
            下一頁
          </button>
        </div>
        <SignalPerformance version={finishVersion} />
    </section>
    </div>
  )
}
