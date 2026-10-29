import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import {
  faChevronDown,
  faChevronLeft,
  faChevronRight,
  faPlay,
  faTriangleExclamation,
} from '@fortawesome/free-solid-svg-icons'
import { IconButton } from '../../components/IconButton'
import { formatTaipeiTime } from '../../lib/time'
import { Fragment, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../../api/client'
import { PageHeader } from '../../components/PageHeader'
import { EquityCurveChart } from './EquityCurveChart'
import { TradeKlineChart } from './TradeKlineChart'
import { summarizeRule } from './summary'
import type { WatchRule } from '../rules/types'
import type { CostSnapshot, Detail, Metrics, Report, StockPerformance } from './types'

const percent = (n: number | null | undefined) => (n == null ? '無資料' : `${(n * 100).toFixed(2)}%`)
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
const metricHeaders = ['交易次數', '淨勝率', '平均淨報酬', '淨複利報酬', '淨最大回撤', '淨獲利因子', '超額報酬（vs 0050）']
function CostInfo({ costs }: { costs: CostSnapshot | null }) {
  if (!costs) return <p className="backtest-warning">舊結果未記錄成本，需重新回測。</p>
  return <p className="muted">本次成本：買賣手續費各 {(costs.feeRate * 100).toFixed(4)}% × {costs.feeDiscount}；
    賣出證交稅：普通股 {percent(costs.taxRateStock)}、ETF {percent(costs.taxRateEtf)}。</p>
}
function MetricCells({ metrics: m, benchmarkBuyHoldReturn, overall = false }: { metrics: Metrics; benchmarkBuyHoldReturn: number | null; overall?: boolean }) {
  if (m.tradeCount === 0) return <td className="muted" colSpan={metricHeaders.length}>期間內無訊號</td>
  const excess = m.compoundReturn === null || benchmarkBuyHoldReturn === null
    ? null : m.compoundReturn - benchmarkBuyHoldReturn
  return (
    <>
      <td>
        {m.tradeCount}
        {m.insufficientSample && <small className="backtest-warning">樣本不足</small>}
      </td>
      <td>{percent(m.winRate)}</td>
      <td>{percent(m.averageReturn)}</td>
      <td>{percent(m.compoundReturn)}</td>
      <td>{overall
        ? <>中位數 {percent(m.maxDrawdownMedian)}／最大 {percent(m.maxDrawdownMax)}{m.maxDrawdownMaxTicker && `（${m.maxDrawdownMaxTicker}${m.maxDrawdownMaxName ? ` ${m.maxDrawdownMaxName}` : ''}）`}</>
        : percent(m.maxDrawdown)}</td>
      <td>{!m.tradeCount ? '無資料' : m.noLosses ? '無虧損' : m.profitFactor?.toFixed(2) ?? '無資料'}</td>
      <td>{excess === null ? '—' : `${excess > 0 ? '+' : ''}${percent(excess)}`}</td>
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
  const needsRerun = stock.needsRerun || data?.needsRerun
  const rerunReason = stock.rerunReason ?? data?.rerunReason
    ?? '需重新回測：以下舊報酬只代表毛報酬。'
  return (
    <div className="backtest-detail">
      <h2>
        {stock.ticker} {stock.stockName} · {stock.ruleName}
        {(stock.stale || data?.stale) && <span className="stale-mark" title="以下為上次成功結果，已過期。"><FontAwesomeIcon icon={faTriangleExclamation} /></span>}
        {needsRerun && <span className="stale-mark" title={rerunReason}><FontAwesomeIcon icon={faTriangleExclamation} /></span>}
      </h2>
      <div className="muted backtest-detail-summary">
        <p>毛報酬：勝率 {percent(stock.grossMetrics.winRate)}、平均 {percent(stock.grossMetrics.averageReturn)}、複利 {percent(stock.grossMetrics.compoundReturn)}、最大回撤 {percent(stock.grossMetrics.maxDrawdown)}、獲利因子 {stock.grossMetrics.noLosses ? '無虧損' : stock.grossMetrics.profitFactor?.toFixed(2) ?? '無資料'}</p>
        <p>平均超額報酬 {percent(stock.averageExcessReturn)}{stock.benchmarkReason && `；${stock.benchmarkReason}`}</p>
        <p>持有中 {stock.openCount} 筆、未成交 {stock.unfilledCount} 筆</p>
        <p>略過 {stock.skippedSessions} 個無有效行情日</p>
      </div>
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
          <CostInfo costs={data.costSnapshot} />
          {data.warnings.map((w) => <p key={w} className="backtest-warning">{w}</p>)}
          {data.benchmarkReason && <p className="muted">{data.benchmarkReason}</p>}
          <div className="backtest-charts">
            <section>
              <h3>資金曲線</h3>
              <EquityCurveChart curve={data.equityCurve} />
            </section>
            <section>
              <h3>K 線與買賣點</h3>
              <TradeKlineChart ticker={stock.ticker} start={stock.actualStart} end={stock.actualEnd} markers={data.tradeMarkers} />
            </section>
          </div>
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
                    '已實現淨／毛報酬',
                    '未實現淨／毛報酬',
                    '0050／超額報酬',
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
                    <td>{percent(t.netReturnRate)}{needsRerun && <span className="stale-mark" title={rerunReason}><FontAwesomeIcon icon={faTriangleExclamation} /></span>}
                      <small>毛 {percent(data.needsRerun ? t.returnRate : t.grossReturnRate)}</small></td>
                    <td>
                      {percent(t.netUnrealizedReturn)}{needsRerun && <span className="stale-mark" title={rerunReason}><FontAwesomeIcon icon={faTriangleExclamation} /></span>}
                      <small>毛 {percent(data.needsRerun ? t.unrealizedReturn : t.grossUnrealizedReturn)}</small>
                      {t.valuationDate && <small>估值日 {t.valuationDate}</small>}
                    </td>
                    <td>{percent(t.benchmarkReturn)}<small>超額 {percent(t.excessReturn)}</small>
                      {t.benchmarkReason && <small>{t.benchmarkReason}</small>}</td>
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
            <IconButton disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 50))} icon={faChevronLeft} label="上一頁" />
            <span>第 {Math.floor(offset / 50) + 1} 頁 · 交易與訊號每頁各 50 筆</span>
            <IconButton
              disabled={offset + 50 >= Math.max(data.tradeTotal, data.signalTotal)}
              onClick={() => setOffset(offset + 50)}
              icon={faChevronRight}
              label="下一頁"
           />
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
  const staleInfo = report.data?.staleInfo
  const staleRuleIds = (staleInfo?.ruleIds ?? []).filter((id) => active.some((r) => r.id === id))
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
        Number(a.metrics.tradeCount === 0) - Number(b.metrics.tradeCount === 0) ||
        Number(a.metrics.insufficientSample) - Number(b.metrics.insufficientSample) ||
        (b.metrics[sort] ?? -Infinity) - (a.metrics[sort] ?? -Infinity) ||
        a.ticker.localeCompare(b.ticker),
    )
  return (
    <section className="backtest-page">
      <PageHeader title="戰法回測" description="以最近三年的歷史訊號與模擬交易，檢視戰法表現。" />
      {staleInfo && (
        <div className="backtest-stale-banner" role="status">
          <span>{staleInfo.reason === 'definition' && staleInfo.changedAt
            ? `戰法定義已於 ${formatTaipeiTime(staleInfo.changedAt)}（台北時間）變更，以下結果已過期。`
            : '以下結果已過期，請重新回測。'}</span>
          <button
            className="button-primary"
            disabled={running || start.isPending || !staleRuleIds.length}
            onClick={() => start.mutate(staleRuleIds)}
          >
            <FontAwesomeIcon icon={faPlay} />
            立即重新回測
          </button>
        </div>
      )}
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
          <FontAwesomeIcon icon={faPlay} />
          {running || start.isPending ? '回測執行中…' : '執行回測'}
        </button>
        {start.isError && (
          <p role="alert" className="error-text">
            {start.error.message}
          </p>
        )}
        {task && (
          <div className="schedule-summary" role="status">
            <CostInfo costs={task.costSnapshot} />
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
        <p>訊號後下一有效交易日開盤成交；淨報酬包含買賣手續費與賣出證交稅。未模擬最低手續費 20 元、滑價或當沖稅率，也不額外將股利再投入。</p>
        <p>
          0050 為不扣成本的還原報酬，超額報酬為淨報酬減 0050。複利報酬與最大回撤僅依已完成交易計算，不含持倉期間浮動損益。跨股票複利僅供比較，不是實際投資組合績效。
        </p>
        <p>少於 10 筆已完成交易標示樣本不足；上市較晚或需較長指標暖機的股票，實際期間可能較短。</p>
        <p>還原價格已依證交所與櫃買中心公告的分割、減資事件調整。</p>
      </div>
      {task && (
        <>
          <div className="card">
            <h2>戰法整體績效</h2>
            {[...new Map(stocks.map((s) => [s.ruleId, s.ruleName])).entries()].map(([ruleId, ruleName]) => {
              const summary = summarizeRule(stocks, ruleId)
              const benchmark = report.data?.overall.find((row) => row.ruleId === ruleId)?.benchmarkBuyHoldReturn
              return <p key={ruleId}>{ruleName}：{summary.stockCount} 檔中 {summary.signalStockCount} 檔有訊號，共 {summary.tradeCount} 筆交易；{summary.beatBenchmarkCount} 檔贏過同期 0050{benchmark != null && `（${percent(benchmark)}）`}。{summary.sampleSufficient
                ? `中位數淨勝率 ${percent(summary.medianWinRate)}。`
                : '樣本不足，勝率僅供參考。'}</p>
            })}
            <p className="muted">
              統計下方個股結果，舊格式未含淨報酬者除外；期間顯示最早至最晚日期，各股涵蓋長度可能不同。
            </p>
            <div className="table-scroll">
              <table className={staleInfo ? 'data-table backtest-stale' : 'data-table'}>
                <thead>
                  <tr>
                    <th>戰法／股票數</th>
                    {metricHeaders.map((h) => (
                      <th key={h} title={h === '超額報酬（vs 0050）' ? '淨複利報酬 − 同期 0050 買進持有' : undefined}>{h === '淨複利報酬' ? '個股淨複利中位數' : h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {report.data?.overall.map((r) => (
                    <tr key={r.ruleId} className={r.metrics.tradeCount === 0 || r.metrics.insufficientSample ? 'backtest-row-thin' : undefined}>
                      <td>
                        {r.ruleName}
                        {r.stale && <span className="stale-mark" title="結果已過期，請重新回測。"><FontAwesomeIcon icon={faTriangleExclamation} /></span>}
                        <small>{r.stockCount} 檔</small>
                        <small>{r.actualStart}～{r.actualEnd}</small>
                      </td>
                      <MetricCells overall metrics={r.metrics} benchmarkBuyHoldReturn={r.benchmarkBuyHoldReturn} />
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {report.data?.overall.length === 0 && <p>本次尚無成功回測股票。</p>}
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
              <table className={staleInfo ? 'data-table backtest-stale' : 'data-table'}>
                <thead>
                  <tr>
                    <th>股票／戰法</th>
                    {metricHeaders.map((h) => (
                      <th key={h} title={h === '超額報酬（vs 0050）' ? '淨複利報酬 − 同期 0050 買進持有' : undefined}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {visible.map((s) => (
                    <Fragment key={s.id}>
                      <tr className={s.metrics.tradeCount === 0 || s.metrics.insufficientSample ? 'backtest-row-thin' : undefined}>
                        <td>
                          <button
                            className="row-link backtest-stock-toggle"
                            aria-expanded={selected === s.id}
                            aria-controls={selected === s.id ? `backtest-detail-${s.id}` : undefined}
                            onClick={() => setSelected(selected === s.id ? null : s.id)}
                          >
                            <FontAwesomeIcon icon={selected === s.id ? faChevronDown : faChevronRight} /> {s.ticker} {s.stockName}
                          </button>
                          <small>{s.ruleName}</small>
                          {s.needsRerun && <span className="stale-mark" title={s.rerunReason ?? '需重新回測：以下舊報酬只代表毛報酬。'}><FontAwesomeIcon icon={faTriangleExclamation} /></span>}
                          {s.stale && (
                            <span className="stale-mark" title="過期：上次成功結果"><FontAwesomeIcon icon={faTriangleExclamation} /></span>
                          )}
                          <small>{s.actualStart}～{s.actualEnd}</small>
                        </td>
                        <MetricCells metrics={s.metrics} benchmarkBuyHoldReturn={s.benchmarkBuyHoldReturn} />
                      </tr>
                      {selected === s.id && (
                        <tr className="backtest-detail-row" id={`backtest-detail-${s.id}`}>
                          <td colSpan={metricHeaders.length + 1}>
                            <TradeDetails key={`${s.id}-${s.calculatedAt}`} stock={s} batch={task.batchId} />
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  ))}
                </tbody>
              </table>
            </div>
            {!visible.length && <p>沒有符合篩選條件的結果。</p>}
          </div>
        </>
      )}
    </section>
  )
}
