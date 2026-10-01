import { PageHeader } from '../../components/PageHeader'
import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
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

export function StockLookupPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const location = useLocation()
  const from = (location.state as { from?: string } | null)?.from ?? '/'
  const tickerFromUrl = searchParams.get('ticker')

  const [selectedTicker, setSelectedTicker] = useState(tickerFromUrl ?? '')
  const [emaVisibility, setEmaVisibility] = useState<EmaVisibility>({
    ema10: true,
    ema20: true,
    ema60: true,
  })
  const [bollingerVisible, setBollingerVisible] = useState(true)
  const [subPanelIndicator, setSubPanelIndicator] = useState<SubPanelIndicator>('kd')

  const stocksQuery = useQuery({
    queryKey: ['stocks'],
    queryFn: () => apiClient.get<StockInfo[]>('/stocks?limit=50'),
  })

  // 股票清單載入後，如果目前還沒選定股票(例如直接進這頁、URL沒帶ticker)，預設選第一檔。
  useEffect(() => {
    if (!selectedTicker && stocksQuery.data && stocksQuery.data.length > 0) {
      setSelectedTicker(stocksQuery.data[0].ticker)
    }
  }, [selectedTicker, stocksQuery.data])

  const handleSelectTicker = (ticker: string) => {
    setSelectedTicker(ticker)
    setSearchParams({ ticker })
  }

  const profile = useQuery({
    queryKey: ['stock-profile', selectedTicker],
    queryFn: () => apiClient.get<StockInfo & { sector: string }>(`/stocks/${selectedTicker}`),
    enabled: Boolean(selectedTicker),
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
        {stocksQuery.isLoading && <p className="muted">讀取中...</p>}
        {stocksQuery.data && (
          <select value={selectedTicker} onChange={(e) => handleSelectTicker(e.target.value)}>
            {stocksQuery.data.map((stock) => (
              <option key={stock.ticker} value={stock.ticker}>
                {stock.ticker} {stock.name}
              </option>
            ))}
          </select>
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
            emaVisibility={emaVisibility}
            bollingerVisible={bollingerVisible}
            subPanelIndicator={subPanelIndicator}
          />
        )}
      </div>

      <div className="card">
        <h3>目前技術指標</h3>
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
