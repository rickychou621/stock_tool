import { expect, it } from 'vitest'
import { pickIndicators } from './indicators'

it('依五個指定標籤排序與去重，其他指標保留於 tooltip 資料', () => {
  const result = pickIndicators({
    'ma_touch_rebound.prev_close': 55,
    'ma_rising.ma': 56.18,
    'ma_touch_rebound.ma': 56.19,
    'ma_rising.ma_prev': 54,
    'ma_touch_rebound.close': 57,
    'ma_touch_rebound.close_distance_pct': 0.0146,
    'ma_rising.slope_pct': 0.02,
  })
  expect(result.shown.map(({ label, value }) => [label, value])).toEqual([
    ['月線', '56.18'], ['月線斜率', '+2.00%'], ['距月線', '+1.46%'],
    ['收盤價', '57'], ['前日收盤', '55'],
  ])
  expect(result.hidden.map(({ label, value }) => `${label} ${value}`).join('、'))
    .toBe('月線 56.19、5 日前月線 54')
})
it('缺少指標不補值，空資料維持空白', () => {
  expect(pickIndicators({})).toEqual({ shown: [], hidden: [] })
  expect(pickIndicators({ 'price_touch_ma.ma': null }).shown[0].value).toBe('無資料')
})
