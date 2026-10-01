import type { PriceBar } from '../types'

export interface LinePoint {
  time: string
  value: number
}

export interface KdPoint {
  time: string
  k: number
  d: number
}

export interface BollingerPoint {
  time: string
  upper: number
  mid: number
  lower: number
}

export interface MacdPoint {
  time: string
  dif: number
  signal: number
  histogram: number
}

function emaSeries(values: number[], period: number): number[] {
  const smoothing = 2 / (period + 1)
  const result: number[] = []
  let previousEma: number | undefined

  values.forEach((value) => {
    previousEma =
      previousEma === undefined ? value : value * smoothing + previousEma * (1 - smoothing)
    result.push(previousEma)
  })

  return result
}

export function calculateEMA(bars: PriceBar[], period: number): LinePoint[] {
  return emaSeries(
    bars.map((bar) => bar.close),
    period,
  ).map((value, index) => ({ time: bars[index].date, value: Number(value.toFixed(2)) }))
}

// MACD：DIF=短期EMA-長期EMA，訊號線=DIF的EMA，柱狀體=DIF-訊號線。跟後端calculate_macd邏輯一致，
// 只是這裡用日K(跟K線圖同一份資料)而不是月K(後端條件評估用的是月K)。
export function calculateMACD(
  bars: PriceBar[],
  shortPeriod = 12,
  longPeriod = 26,
  signalPeriod = 9,
): MacdPoint[] {
  const closes = bars.map((bar) => bar.close)
  const emaShort = emaSeries(closes, shortPeriod)
  const emaLong = emaSeries(closes, longPeriod)
  const dif = emaShort.map((value, index) => value - emaLong[index])
  const signal = emaSeries(dif, signalPeriod)

  return bars.map((bar, index) => ({
    time: bar.date,
    dif: Number(dif[index].toFixed(2)),
    signal: Number(signal[index].toFixed(2)),
    histogram: Number((dif[index] - signal[index]).toFixed(2)),
  }))
}

// 標準KD(隨機指標)計算：RSV為n日內的相對位置，K/D再各自用2/3前值+1/3新值平滑。
export function calculateKD(bars: PriceBar[], period = 9): KdPoint[] {
  const result: KdPoint[] = []
  let previousK = 50
  let previousD = 50

  bars.forEach((bar, index) => {
    const window = bars.slice(Math.max(0, index - period + 1), index + 1)
    const highest = Math.max(...window.map((b) => b.high))
    const lowest = Math.min(...window.map((b) => b.low))
    const rsv = highest === lowest ? 50 : ((bar.close - lowest) / (highest - lowest)) * 100

    const k = (previousK * 2 + rsv) / 3
    const d = (previousD * 2 + k) / 3
    previousK = k
    previousD = d

    result.push({ time: bar.date, k: Number(k.toFixed(2)), d: Number(d.toFixed(2)) })
  })

  return result
}

// 布林通道：中軌=period日SMA，上下軌=中軌 ± numStd倍標準差(母體標準差，跟後端
// bollinger_mid_up條件算中軌的方式一致)。資料不足period筆前的日期不畫，避免失真的窄帶。
export function calculateBollingerBands(
  bars: PriceBar[],
  period = 20,
  numStd = 2,
): BollingerPoint[] {
  const result: BollingerPoint[] = []

  for (let i = period - 1; i < bars.length; i++) {
    const window = bars.slice(i - period + 1, i + 1)
    const mid = window.reduce((sum, b) => sum + b.close, 0) / period
    const variance = window.reduce((sum, b) => sum + (b.close - mid) ** 2, 0) / period
    const std = Math.sqrt(variance)

    result.push({
      time: bars[i].date,
      upper: Number((mid + numStd * std).toFixed(2)),
      mid: Number(mid.toFixed(2)),
      lower: Number((mid - numStd * std).toFixed(2)),
    })
  }

  return result
}
