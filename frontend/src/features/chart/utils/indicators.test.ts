import { expect, it } from 'vitest'
import { calculateSMA } from './indicators'

const bars = [10, 20, 30, 40].map((close, index) => ({
  date: `2026-10-0${index + 1}`, open: close, high: close, low: close, close, volume: 100,
}))
it('SMA 滿足期數才開始繪製，並以移動視窗平均收盤價', () => {
  expect(calculateSMA(bars, 3)).toEqual([
    { time: '2026-10-03', value: 20 }, { time: '2026-10-04', value: 30 },
  ])
  expect(calculateSMA(bars, 1)).toEqual(bars.map((bar) => ({ time: bar.date, value: bar.close })))
})
it('空資料、不足期數或無效期數不產生月線', () => {
  expect(calculateSMA([], 20)).toEqual([])
  expect(calculateSMA(bars, 20)).toEqual([])
  expect(calculateSMA(bars, 0)).toEqual([])
})
it('SMA 顯示到小數點兩位', () => {
  expect(calculateSMA([...bars.slice(0, 2), { ...bars[2], close: 31 }], 3)[0].value).toBe(20.33)
})
