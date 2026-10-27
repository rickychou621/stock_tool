import { useEffect, useRef } from 'react'
import { createChart, LineSeries, PriceScaleMode, type Time } from 'lightweight-charts'
import type { EquityCurve } from './types'

export function EquityCurveChart({ curve }: { curve: EquityCurve }) {
  const container = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!container.current || !curve.strategy.length) return
    const dark = window.matchMedia('(prefers-color-scheme: dark)').matches
    const theme = dark
      ? { background: '#1b2633', text: '#e8eef4', grid: '#354454', accent: '#80d5c7' }
      : { background: '#ffffff', text: '#202d3a', grid: '#dce3e8', accent: '#126e68' }
    const chart = createChart(container.current, {
      width: container.current.clientWidth,
      height: 260,
      layout: { background: { color: theme.background }, textColor: theme.text },
      grid: { vertLines: { color: theme.grid }, horzLines: { color: theme.grid } },
      localization: { dateFormat: 'yyyy/MM/dd' },
      // Three years of daily bars must fit in a half-width panel.
      timeScale: { minBarSpacing: 0.1 },
      rightPriceScale: { mode: PriceScaleMode.Logarithmic },
    })
    for (const [points, color] of [[curve.strategy, theme.accent], [curve.benchmark, '#888888']] as const) {
      const series = chart.addSeries(LineSeries, {
        color,
        priceFormat: { type: 'custom', formatter: (value: number) => `${((value - 1) * 100).toFixed(2)}%` },
      })
      series.setData(points.map((point) => ({ time: point.date as Time, value: point.value })))
    }
    // The detail row is still expanding on first paint; resize and refit once it has its real width.
    const observer = new ResizeObserver(([entry]) => {
      chart.resize(entry.contentRect.width, 260)
      chart.timeScale().fitContent()
    })
    observer.observe(container.current)
    return () => {
      observer.disconnect()
      chart.remove()
    }
  }, [curve])

  if (!curve.strategy.length) return <p className="muted">沒有足夠資料畫資金曲線</p>
  return <>
    <div ref={container} style={{ height: 260 }} />
    <p className="backtest-chart-legend"><span>— 戰法</span><span>— 同期 0050</span></p>
  </>
}
