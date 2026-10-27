import { useEffect, useRef } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  CandlestickSeries, createChart, createSeriesMarkers, PriceScaleMode, type SeriesMarker, type Time,
} from 'lightweight-charts'
import { apiClient } from '../../api/client'
import type { PriceBar } from '../chart/types'
import type { TradeMarker } from './types'

interface Props {
  ticker: string
  start: string
  end: string
  markers: TradeMarker[]
}

export function TradeKlineChart({ ticker, start, end, markers }: Props) {
  const container = useRef<HTMLDivElement>(null)
  const history = useQuery({
    queryKey: ['backtest-kline', ticker, start, end],
    queryFn: () => apiClient.get<PriceBar[]>(`/chart/${ticker}?start=${start}&end=${end}`),
  })
  const bars = history.data
  useEffect(() => {
    if (!container.current || !bars?.length) return
    const dark = window.matchMedia('(prefers-color-scheme: dark)').matches
    const theme = dark
      ? { background: '#1b2633', text: '#e8eef4', grid: '#354454' }
      : { background: '#ffffff', text: '#202d3a', grid: '#dce3e8' }
    const chart = createChart(container.current, {
      width: container.current.clientWidth,
      height: 320,
      layout: { background: { color: theme.background }, textColor: theme.text },
      grid: { vertLines: { color: theme.grid }, horzLines: { color: theme.grid } },
      localization: { dateFormat: 'yyyy/MM/dd' },
      // Three years of daily bars must fit in a half-width panel.
      timeScale: { minBarSpacing: 0.1 },
      rightPriceScale: { mode: PriceScaleMode.Logarithmic },
    })
    const series = chart.addSeries(CandlestickSeries, {
      upColor: '#d03b3b', downColor: '#0ca30c',
      borderUpColor: '#d03b3b', borderDownColor: '#0ca30c',
      wickUpColor: '#d03b3b', wickDownColor: '#0ca30c',
    })
    series.setData(bars.map((bar) => ({ ...bar, time: bar.date as Time })))
    const dates = new Set(bars.map((bar) => bar.date))
    const points: SeriesMarker<Time>[] = markers
      .filter((marker) => dates.has(marker.date))
      .sort((a, b) => a.date.localeCompare(b.date))
      .map((marker) => ({
        time: marker.date as Time,
        position: marker.side === 'buy' ? 'belowBar' : 'aboveBar',
        shape: marker.side === 'buy' ? 'arrowUp' : 'arrowDown',
        color: marker.side === 'buy' ? '#d03b3b' : '#0ca30c',
      }))
    createSeriesMarkers(series, points)
    // The detail row is still expanding on first paint; resize and refit once it has its real width.
    const observer = new ResizeObserver(([entry]) => {
      chart.resize(entry.contentRect.width, 320)
      chart.timeScale().fitContent()
    })
    observer.observe(container.current)
    return () => {
      observer.disconnect()
      chart.remove()
    }
  }, [bars, markers])

  if (history.isPending) return <p className="muted">讀取 K 線…</p>
  if (history.isError) return <p role="alert" className="error-text">K 線讀取失敗。</p>
  if (!bars?.length) return <p className="muted">沒有足夠資料畫 K 線</p>
  return <>
    <div ref={container} style={{ height: 320 }} />
    <p className="backtest-chart-legend"><span className="buy">▲ 買進</span><span className="sell">▼ 賣出</span></p>
  </>
}
