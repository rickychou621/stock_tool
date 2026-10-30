import { expect, it } from 'vitest'
import { formatRuleMetrics } from './ruleMetrics'

it('三項指標使用固定精度與單位', () => {
  expect(formatRuleMetrics({ maDistancePct: 0.92, maSlopePct: 0.64, stopDistancePct: -2.1 }).join('｜'))
    .toBe('距月線 +0.9%｜月線斜率 +0.64%／5 日｜停損距離 -2.1%')
})
it('省略缺值且不顯示負零', () => {
  expect(formatRuleMetrics({ maDistancePct: null })).toEqual([])
  expect(formatRuleMetrics({ maDistancePct: -0.01, maSlopePct: 0, stopDistancePct: 0 }))
    .toEqual(['距月線 0.0%', '月線斜率 0.00%／5 日', '停損距離 0.0%'])
})
