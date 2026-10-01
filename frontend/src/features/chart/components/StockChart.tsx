import { useEffect, useRef, useState } from 'react'
import {
  CandlestickSeries,
  HistogramSeries,
  LineSeries,
  LineStyle,
  createChart,
  type CandlestickData,
  type IChartApi,
  type ISeriesApi,
  type LineData,
  type Time,
} from 'lightweight-charts'
import type { PriceBar } from '../types'
import {
  calculateBollingerBands,
  calculateEMA,
  calculateKD,
  calculateMACD,
} from '../utils/indicators'

// 台股慣例「紅漲綠跌」，跟lightweight-charts預設的美式配色(漲綠跌紅)相反，需自行指定。
const UP_COLOR = '#d03b3b'
const DOWN_COLOR = '#0ca30c'

// EMA疊加線顏色刻意不用紅/綠，避免跟K棒漲跌色混淆。
const EMA_COLORS = { ema10: '#2a78d6', ema20: '#eb6834', ema60: '#4a3aa7' } as const
const KD_COLORS = { k: '#2a78d6', d: '#eb6834' } as const
// 布林通道另外挑跟EMA不同的色系(aqua/magenta)，避免同一張圖上疊線混淆。
const BOLLINGER_MID_COLOR = '#1baf7a'
const BOLLINGER_BAND_COLOR = '#e87ba4'
const MACD_COLORS = { dif: '#2a78d6', signal: '#eb6834' } as const
const MACD_HISTOGRAM_UP_COLOR = '#d03b3b'
const MACD_HISTOGRAM_DOWN_COLOR = '#0ca30c'

export type SubPanelIndicator = 'kd' | 'macd'

const LIGHT_THEME = { background: '#ffffff', text: '#202d3a', grid: '#dce3e8' }
const DARK_THEME = { background: '#1b2633', text: '#e8eef4', grid: '#354454' }

export interface EmaVisibility {
  ema10: boolean
  ema20: boolean
  ema60: boolean
}

interface OhlcInfo {
  open: number
  high: number
  low: number
  close: number
}

interface KdInfo {
  k: number
  d: number
}

interface MacdInfo {
  dif: number
  signal: number
  histogram: number
}

interface StockChartProps {
  bars: PriceBar[]
  emaVisibility: EmaVisibility
  bollingerVisible: boolean
  subPanelIndicator: SubPanelIndicator
}

export function StockChart({
  bars,
  emaVisibility,
  bollingerVisible,
  subPanelIndicator,
}: StockChartProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const emaSeriesRef = useRef<Record<keyof EmaVisibility, ISeriesApi<'Line'> | null>>({
    ema10: null,
    ema20: null,
    ema60: null,
  })
  const bollingerSeriesRef = useRef<{
    upper: ISeriesApi<'Line'> | null
    mid: ISeriesApi<'Line'> | null
    lower: ISeriesApi<'Line'> | null
  }>({ upper: null, mid: null, lower: null })
  const kdSeriesRef = useRef<{ k: ISeriesApi<'Line'> | null; d: ISeriesApi<'Line'> | null }>({
    k: null,
    d: null,
  })
  const macdSeriesRef = useRef<{
    dif: ISeriesApi<'Line'> | null
    signal: ISeriesApi<'Line'> | null
    histogram: ISeriesApi<'Histogram'> | null
  }>({ dif: null, signal: null, histogram: null })
  const [ohlcInfo, setOhlcInfo] = useState<OhlcInfo | null>(null)
  const [kdInfo, setKdInfo] = useState<KdInfo | null>(null)
  const [macdInfo, setMacdInfo] = useState<MacdInfo | null>(null)

  useEffect(() => {
    const container = containerRef.current
    if (!container || bars.length === 0) return

    const isDark = window.matchMedia('(prefers-color-scheme: dark)').matches
    const theme = isDark ? DARK_THEME : LIGHT_THEME

    const chart: IChartApi = createChart(container, {
      autoSize: true,
      layout: {
        background: { color: theme.background },
        textColor: theme.text,
      },
      grid: {
        vertLines: { color: theme.grid },
        horzLines: { color: theme.grid },
      },
      // 滑鼠移到K棒上時，X軸/crosshair顯示的日期格式固定用 2026/09/24 這種格式，
      // 不用預設的 "28 8月 '26"(受瀏覽器locale影響、格式也不好讀)。
      localization: { dateFormat: 'yyyy/MM/dd' },
      timeScale: { borderColor: theme.grid },
      rightPriceScale: { borderColor: theme.grid },
    })

    // pane 0：K線 + EMA疊加線 + 布林通道
    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: UP_COLOR,
      downColor: DOWN_COLOR,
      borderUpColor: UP_COLOR,
      borderDownColor: DOWN_COLOR,
      wickUpColor: UP_COLOR,
      wickDownColor: DOWN_COLOR,
    })
    const candleData = bars.map((bar) => ({
      time: bar.date as Time,
      open: bar.open,
      high: bar.high,
      low: bar.low,
      close: bar.close,
    }))
    candleSeries.setData(candleData)

    const emaPeriods: Array<[keyof EmaVisibility, number]> = [
      ['ema10', 10],
      ['ema20', 20],
      ['ema60', 60],
    ]
    emaPeriods.forEach(([key, period]) => {
      const series = chart.addSeries(LineSeries, {
        color: EMA_COLORS[key],
        lineWidth: 2,
        visible: emaVisibility[key],
        priceLineVisible: false,
        lastValueVisible: false,
      })
      series.setData(calculateEMA(bars, period))
      emaSeriesRef.current[key] = series
    })

    const bollinger = calculateBollingerBands(bars)
    const upperSeries = chart.addSeries(LineSeries, {
      color: BOLLINGER_BAND_COLOR,
      lineWidth: 1,
      lineStyle: LineStyle.Dashed,
      visible: bollingerVisible,
      priceLineVisible: false,
      lastValueVisible: false,
    })
    upperSeries.setData(bollinger.map((p) => ({ time: p.time as Time, value: p.upper })))

    const midSeries = chart.addSeries(LineSeries, {
      color: BOLLINGER_MID_COLOR,
      lineWidth: 1,
      visible: bollingerVisible,
      priceLineVisible: false,
      lastValueVisible: false,
    })
    midSeries.setData(bollinger.map((p) => ({ time: p.time as Time, value: p.mid })))

    const lowerSeries = chart.addSeries(LineSeries, {
      color: BOLLINGER_BAND_COLOR,
      lineWidth: 1,
      lineStyle: LineStyle.Dashed,
      visible: bollingerVisible,
      priceLineVisible: false,
      lastValueVisible: false,
    })
    lowerSeries.setData(bollinger.map((p) => ({ time: p.time as Time, value: p.lower })))

    bollingerSeriesRef.current = { upper: upperSeries, mid: midSeries, lower: lowerSeries }

    // pane 1：KD或MACD對照圖，兩組線都畫出來，用visible切換顯示哪一組(下拉選單控制)，
    // 這樣切換時不用重建圖表，也能同時保留兩邊的crosshair資料可以讀。
    const showKd = subPanelIndicator === 'kd'
    const showMacd = subPanelIndicator === 'macd'

    const kd = calculateKD(bars)
    const kSeries = chart.addSeries(
      LineSeries,
      {
        color: KD_COLORS.k,
        lineWidth: 2,
        visible: showKd,
        priceLineVisible: false,
        lastValueVisible: false,
      },
      1,
    )
    const kData = kd.map((point) => ({ time: point.time as Time, value: point.k }))
    kSeries.setData(kData)

    const dSeries = chart.addSeries(
      LineSeries,
      {
        color: KD_COLORS.d,
        lineWidth: 2,
        visible: showKd,
        priceLineVisible: false,
        lastValueVisible: false,
      },
      1,
    )
    const dData = kd.map((point) => ({ time: point.time as Time, value: point.d }))
    dSeries.setData(dData)
    kdSeriesRef.current = { k: kSeries, d: dSeries }

    const macd = calculateMACD(bars)
    const histogramSeries = chart.addSeries(
      HistogramSeries,
      { visible: showMacd, priceLineVisible: false, lastValueVisible: false },
      1,
    )
    histogramSeries.setData(
      macd.map((point) => ({
        time: point.time as Time,
        value: point.histogram,
        color: point.histogram >= 0 ? MACD_HISTOGRAM_UP_COLOR : MACD_HISTOGRAM_DOWN_COLOR,
      })),
    )

    const difSeries = chart.addSeries(
      LineSeries,
      {
        color: MACD_COLORS.dif,
        lineWidth: 2,
        visible: showMacd,
        priceLineVisible: false,
        lastValueVisible: false,
      },
      1,
    )
    difSeries.setData(macd.map((point) => ({ time: point.time as Time, value: point.dif })))

    const macdSignalSeries = chart.addSeries(
      LineSeries,
      {
        color: MACD_COLORS.signal,
        lineWidth: 2,
        visible: showMacd,
        priceLineVisible: false,
        lastValueVisible: false,
      },
      1,
    )
    macdSignalSeries.setData(
      macd.map((point) => ({ time: point.time as Time, value: point.signal })),
    )
    macdSeriesRef.current = { dif: difSeries, signal: macdSignalSeries, histogram: histogramSeries }

    chart.panes()[1]?.setStretchFactor(0.3)
    chart.timeScale().fitContent()

    // 預設(還沒hover時)顯示最後一根K棒/最新KD、MACD值，跟大部分看盤軟體行為一致。
    const lastCandle = candleData[candleData.length - 1]
    setOhlcInfo({
      open: lastCandle.open,
      high: lastCandle.high,
      low: lastCandle.low,
      close: lastCandle.close,
    })
    const lastKd = kd[kd.length - 1]
    setKdInfo({ k: lastKd.k, d: lastKd.d })
    const lastMacd = macd[macd.length - 1]
    setMacdInfo({ dif: lastMacd.dif, signal: lastMacd.signal, histogram: lastMacd.histogram })

    // 滑鼠移到某根K棒上時，把那一根的高低點(以及對應的K/D、MACD值)顯示在圖表上方，
    // 滑鼠離開圖表範圍時(param.time為undefined)則還原成顯示最新一根的數值。
    const handleCrosshairMove: Parameters<typeof chart.subscribeCrosshairMove>[0] = (param) => {
      if (!param.time) {
        setOhlcInfo({
          open: lastCandle.open,
          high: lastCandle.high,
          low: lastCandle.low,
          close: lastCandle.close,
        })
        setKdInfo({ k: lastKd.k, d: lastKd.d })
        setMacdInfo({ dif: lastMacd.dif, signal: lastMacd.signal, histogram: lastMacd.histogram })
        return
      }

      const candlePoint = param.seriesData.get(candleSeries) as CandlestickData<Time> | undefined
      if (candlePoint) {
        setOhlcInfo({
          open: candlePoint.open,
          high: candlePoint.high,
          low: candlePoint.low,
          close: candlePoint.close,
        })
      }

      const kPoint = param.seriesData.get(kSeries) as LineData<Time> | undefined
      const dPoint = param.seriesData.get(dSeries) as LineData<Time> | undefined
      if (kPoint && dPoint) {
        setKdInfo({ k: kPoint.value, d: dPoint.value })
      }

      const difPoint = param.seriesData.get(difSeries) as LineData<Time> | undefined
      const signalPoint = param.seriesData.get(macdSignalSeries) as LineData<Time> | undefined
      if (difPoint && signalPoint) {
        setMacdInfo({
          dif: difPoint.value,
          signal: signalPoint.value,
          histogram: Number((difPoint.value - signalPoint.value).toFixed(2)),
        })
      }
    }
    chart.subscribeCrosshairMove(handleCrosshairMove)

    // autoSize靠container自己的ResizeObserver在下一輪才會把canvas撐到實際寬度，
    // 上面那次fitContent很可能是在container還沒撐開前就跑的，導致K棒全部擠在一邊。
    // 自己觀察container尺寸變化，每次變化後重新fitContent一次來修正。
    const resizeObserver = new ResizeObserver(() => {
      chart.timeScale().fitContent()
    })
    resizeObserver.observe(container)

    return () => {
      resizeObserver.disconnect()
      chart.unsubscribeCrosshairMove(handleCrosshairMove)
      chart.remove()
    }
    // 只在bars變動時重建整個圖表；emaVisibility/bollingerVisible/subPanelIndicator的變化
    // 交給下面那幾個effect用applyOptions切換，不需要重新建圖表。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bars])

  useEffect(() => {
    ;(Object.keys(emaVisibility) as Array<keyof EmaVisibility>).forEach((key) => {
      emaSeriesRef.current[key]?.applyOptions({ visible: emaVisibility[key] })
    })
  }, [emaVisibility])

  useEffect(() => {
    bollingerSeriesRef.current.upper?.applyOptions({ visible: bollingerVisible })
    bollingerSeriesRef.current.mid?.applyOptions({ visible: bollingerVisible })
    bollingerSeriesRef.current.lower?.applyOptions({ visible: bollingerVisible })
  }, [bollingerVisible])

  useEffect(() => {
    const showKd = subPanelIndicator === 'kd'
    const showMacd = subPanelIndicator === 'macd'
    kdSeriesRef.current.k?.applyOptions({ visible: showKd })
    kdSeriesRef.current.d?.applyOptions({ visible: showKd })
    macdSeriesRef.current.dif?.applyOptions({ visible: showMacd })
    macdSeriesRef.current.signal?.applyOptions({ visible: showMacd })
    macdSeriesRef.current.histogram?.applyOptions({ visible: showMacd })
  }, [subPanelIndicator])

  const isUp = ohlcInfo ? ohlcInfo.close >= ohlcInfo.open : true

  return (
    <div>
      {ohlcInfo && (
        <div className="chart-info-line" style={{ color: isUp ? UP_COLOR : DOWN_COLOR }}>
          <span>開 {ohlcInfo.open}</span>
          <span>高 {ohlcInfo.high}</span>
          <span>低 {ohlcInfo.low}</span>
          <span>收 {ohlcInfo.close}</span>
        </div>
      )}
      <div ref={containerRef} style={{ height: 480, width: '100%' }} />
      {subPanelIndicator === 'kd' && kdInfo && (
        <div className="chart-info-line">
          <span style={{ color: KD_COLORS.k }}>K(9) {kdInfo.k}</span>
          <span style={{ color: KD_COLORS.d }}>D(9) {kdInfo.d}</span>
        </div>
      )}
      {subPanelIndicator === 'macd' && macdInfo && (
        <div className="chart-info-line">
          <span style={{ color: MACD_COLORS.dif }}>DIF {macdInfo.dif}</span>
          <span style={{ color: MACD_COLORS.signal }}>MACD訊號線 {macdInfo.signal}</span>
          <span
            style={{
              color: macdInfo.histogram >= 0 ? MACD_HISTOGRAM_UP_COLOR : MACD_HISTOGRAM_DOWN_COLOR,
            }}
          >
            柱狀體 {macdInfo.histogram}
          </span>
        </div>
      )}
    </div>
  )
}
