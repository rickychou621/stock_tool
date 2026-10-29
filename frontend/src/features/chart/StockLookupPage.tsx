import type { WatchlistItem } from '../watchlist/types'
import type { RuleEvaluationResult, WatchRule } from '../rules/types'
import { RuleStateBadge, RuleStateLine } from '../rules/components/RuleStateBadge'
import { PageHeader } from '../../components/PageHeader'
import { useEffect, useMemo, useState } from 'react'
import { useQueries, useQuery } from '@tanstack/react-query'
import { Link, useLocation, useSearchParams } from 'react-router-dom'
import { apiClient } from '../../api/client'
import type { StockInfo } from '../../lib/stockDirectory'
import { StockChart, type EmaVisibility, type SubPanelIndicator } from './components/StockChart'
import { EmaToggle } from './components/EmaToggle'
import { BollingerToggle } from './components/BollingerToggle'
import { SubPanelSelector } from './components/SubPanelSelector'
import { IndicatorSummary } from './components/IndicatorSummary'
import { TriggerHistoryList } from './components/TriggerHistoryList'
import type { PriceBar, TriggerHistoryItem } from './types'
import { calculateEMA, calculateKD } from './utils/indicators'

const CHART_BAR_LIMIT = 120
const TRIGGER_HISTORY_LIMIT = 10
const LAST_TICKER_KEY = 'stock-lookup:last-ticker'
const EXIT_COLOR = '#991b1b'
const taipeiDate = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Taipei' })

export function StockLookupPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const location = useLocation()
  const from = (location.state as { from?: string } | null)?.from ?? '/'
  const tickerFromUrl = searchParams.get('ticker')

  const [selectedTicker, setSelectedTicker] = useState(() => {
    if (tickerFromUrl) return tickerFromUrl
    try {
      return localStorage.getItem(LAST_TICKER_KEY) ?? ''
    } catch {
      return ''
    }
  })
  const [selectedName, setSelectedName] = useState('')
  const [searchInput, setSearchInput] = useState<string | null>(null)
  const [debouncedSearch, setDebouncedSearch] = useState('')
  const [emaVisibility, setEmaVisibility] = useState<EmaVisibility>({
    ema10: true,
    ma20: true,
    ema60: true,
  })
  const [bollingerVisible, setBollingerVisible] = useState(true)
  const [subPanelIndicator, setSubPanelIndicator] = useState<SubPanelIndicator>('kd')

  const stocksQuery = useQuery({
    queryKey: ['stocks', { limit: 20 }],
    queryFn: () => apiClient.get<StockInfo[]>('/stocks?limit=20'),
  })

  const watchlistQuery = useQuery({
    queryKey: ['watchlist'],
    queryFn: () => apiClient.get<WatchlistItem[]>('/watchlist?limit=500'),
    enabled: !selectedTicker,
  })

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedSearch(searchInput?.trim() ?? ''), 300)
    return () => window.clearTimeout(timer)
  }, [searchInput])

  const searchQuery = useQuery({
    queryKey: ['stocks', { limit: 20, q: debouncedSearch }],
    queryFn: () => apiClient.get<StockInfo[]>(`/stocks?limit=20&q=${encodeURIComponent(debouncedSearch)}`),
    enabled: searchInput !== null && Boolean(debouncedSearch),
  })
  const lookupQuery = searchInput?.trim() ? searchQuery : stocksQuery
  const searchReady = !searchInput?.trim() || searchInput.trim() === debouncedSearch
  const options = searchReady ? (lookupQuery.data ?? []) : []

  useEffect(() => {
    if (selectedTicker || (!watchlistQuery.data && !watchlistQuery.isError)) return
    const ticker = watchlistQuery.data?.[0]?.ticker ?? stocksQuery.data?.[0]?.ticker
    if (ticker) setSelectedTicker(ticker)
  }, [selectedTicker, watchlistQuery.data, watchlistQuery.isError, stocksQuery.data])

  useEffect(() => {
    if (!selectedTicker) return
    try {
      localStorage.setItem(LAST_TICKER_KEY, selectedTicker)
    } catch {
      // 儲存不可用時仍可查詢股票。
    }
    if (!tickerFromUrl) setSearchParams({ ticker: selectedTicker }, { replace: true })
  }, [selectedTicker, tickerFromUrl, setSearchParams])

  const handleSelectTicker = (ticker: string) => {
    setSelectedTicker(ticker)
    setSearchParams({ ticker })
  }

  const selectStock = (stock: StockInfo) => {
    handleSelectTicker(stock.ticker)
    setSelectedName(stock.name)
    setSearchInput(null)
  }

  const profile = useQuery({
    queryKey: ['stock-profile', selectedTicker],
    queryFn: () => apiClient.get<StockInfo & { sector: string }>(`/stocks/${selectedTicker}`),
    enabled: Boolean(selectedTicker),
  })

  const rulesQuery = useQuery({
    queryKey: ['rules'],
    queryFn: () => apiClient.get<WatchRule[]>('/rules?limit=50'),
  })
  const enabledRules = (rulesQuery.data ?? []).filter((rule) => rule.isEnabled)
  const ruleStates = useQueries({
    queries: enabledRules.map((rule) => ({
      queryKey: ['rule-state', rule.id, selectedTicker],
      queryFn: () =>
        apiClient.get<RuleEvaluationResult>(
          `/rules/${rule.id}/evaluate?ticker=${encodeURIComponent(selectedTicker)}`,
        ),
      enabled: Boolean(selectedTicker),
    })),
  })

  const chartQuery = useQuery({
    queryKey: ['chart', selectedTicker],
    queryFn: () => apiClient.get<PriceBar[]>(`/chart/${selectedTicker}?limit=${CHART_BAR_LIMIT}`),
    enabled: Boolean(selectedTicker),
  })

  const triggerHistoryQuery = useQuery({
    queryKey: ['alerts', { ticker: selectedTicker }],
    queryFn: () =>
      apiClient.get<TriggerHistoryItem[]>(
        `/alerts?ticker=${selectedTicker}&limit=${TRIGGER_HISTORY_LIMIT}`,
      ),
    enabled: Boolean(selectedTicker),
  })

  const priceLines = ruleStates.flatMap((query, index) => {
    const price = query.data?.state?.triggerPrice
    return price == null ? [] : [{ price, title: '', ruleName: enabledRules[index].name, color: EXIT_COLOR }]
  })
  const markers = useMemo(() => (triggerHistoryQuery.data ?? []).flatMap((item) => {
    if (!item.state) return []
    const utcTime = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(item.triggeredAt)
      ? item.triggeredAt : `${item.triggeredAt}Z`
    const timestamp = new Date(utcTime)
    if (Number.isNaN(timestamp.getTime())) return []
    return [{ date: taipeiDate.format(timestamp), state: item.state, ruleName: item.ruleName }]
  }), [triggerHistoryQuery.data])

  const bars = useMemo(() => chartQuery.data ?? [], [chartQuery.data])

  // EMA/KD都是拿真實K棒現場算出來的，跟圖表上疊的線用同一組資料，數字才會對得上。
  const indicators = useMemo(() => {
    if (bars.length === 0) return null
    const ema10 = calculateEMA(bars, 10)
    const ema60 = calculateEMA(bars, 60)
    const kd = calculateKD(bars)
    const latestKd = kd[kd.length - 1]
    return {
      ema10: ema10[ema10.length - 1].value,
      ema60: ema60[ema60.length - 1].value,
      kdK: latestKd.k,
      kdD: latestKd.d,
    }
  }, [bars])

  return (
    <section>
      <Link to={from}>返回清單</Link>
      <PageHeader
        title="個股查詢"
        description="查看價格走勢與技術指標，輔助個股判斷。"
        eyebrow="研究個股"
      />
      <p className="muted">圖表為日K，KD／MACD副圖也以日K計算；戰法三評估使用月K。</p>

      <label className="field">
        <span>選擇股票</span>
        <input
          list="stock-search-options"
          placeholder="輸入代號或股名，例如 1303 或 南亞"
          value={searchInput ?? `${selectedTicker} ${profile.data?.name ?? selectedName}`.trim()}
          onChange={(event) => {
            const value = event.target.value
            const stock = options.find((option) => value === `${option.ticker} ${option.name}`)
            if (stock) selectStock(stock)
            else setSearchInput(value)
          }}
          onKeyDown={(event) => {
            if (event.key !== 'Enter' || event.nativeEvent.isComposing) return
            const stock = options.find((option) => option.ticker === event.currentTarget.value.trim())
            if (stock) {
              event.preventDefault()
              selectStock(stock)
            }
          }}
        />
        <datalist id="stock-search-options">
          {options.map((stock) => (
            <option key={stock.ticker} value={`${stock.ticker} ${stock.name}`} />
          ))}
        </datalist>
        {searchInput !== null && searchReady && lookupQuery.isSuccess && options.length === 0 && (
          <small className="muted">找不到符合的股票</small>
        )}
      </label>

      <div className="stock-profile" aria-live="polite">
        <strong>
          {selectedTicker} {profile.data?.name ?? ''}
        </strong>
        <span className="status-badge">
          族群：
          {profile.isLoading
            ? '讀取中…'
            : profile.isError
              ? '讀取失敗'
              : profile.data?.sector || '未分類'}
        </span>
        <span className="muted">觀察族群分類，可在觀察清單編輯。</span>
      </div>
      <div className="card" aria-live="polite">
        <h3>戰法狀態</h3>
        {rulesQuery.isLoading && <p>判斷中…</p>}
        {rulesQuery.isError && <p className="error-text">戰法狀態讀取失敗</p>}
        {!selectedTicker && <p className="muted">請先選擇股票</p>}
        {rulesQuery.isSuccess && !enabledRules.length && <p className="muted">尚無啟用中的戰法</p>}
        {selectedTicker &&
          enabledRules.map((rule, index) => {
            const query = ruleStates[index]
            const state = query.data?.state
            return (
              <div className="rule-result" key={rule.id}>
                {query.isPending ? (
                  <p>{rule.name}：判斷中…</p>
                ) : query.isError ? (
                  <p className="error-text">{rule.name}：戰法狀態讀取失敗</p>
                ) : state ? (
                  <>
                    <RuleStateBadge ruleName={rule.name} state={state.state} />
                    <RuleStateLine state={state} />
                  </>
                ) : (
                  <p className="muted">{rule.name}：尚無戰法狀態</p>
                )}
              </div>
            )
          })}
      </div>
      <div className="card">
        <EmaToggle visibility={emaVisibility} onChange={setEmaVisibility} />
        <BollingerToggle visible={bollingerVisible} onChange={setBollingerVisible} />
        <SubPanelSelector value={subPanelIndicator} onChange={setSubPanelIndicator} />
        {chartQuery.isLoading && <p className="muted">讀取中...</p>}
        {chartQuery.isError && <p className="error-text">讀取失敗，請確認 backend 是否運行中。</p>}
        {!chartQuery.isLoading && !chartQuery.isError && bars.length === 0 && (
          <p>尚無行情，請先在觀察清單按評估以更新資料。</p>
        )}
        {bars.length > 0 && (
          <StockChart
            bars={bars}
            priceLines={priceLines}
            markers={markers}
            emaVisibility={emaVisibility}
            bollingerVisible={bollingerVisible}
            subPanelIndicator={subPanelIndicator}
          />
        )}
      </div>

      <div className="card">
        <h3>目前技術指標{bars.length > 0 ? `（${bars[bars.length - 1].date.replaceAll('-', '/')}，日K）` : ''}</h3>
        {indicators && <IndicatorSummary indicators={indicators} />}
      </div>

      <div className="card">
        <h3>歷史觸發紀錄</h3>
        {triggerHistoryQuery.isLoading && <p className="muted">讀取中...</p>}
        {triggerHistoryQuery.data && <TriggerHistoryList items={triggerHistoryQuery.data} />}
      </div>
    </section>
  )
}
