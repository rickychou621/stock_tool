import { expect, it } from 'vitest'
import { formatRuleMetrics, isLargeStopDistance } from './ruleMetrics'

it('三項指標使用固定精度與單位', () => {
  expect(formatRuleMetrics({ maDistancePct: 0.92, maSlopePct: 0.64, stopDistancePct: -2.1 }).join('｜'))
    .toBe('距月線 +0.9%｜月線斜率 +0.64%／5 日｜停損距離 -2.1%')
})
it('省略缺值且不顯示負零', () => {
  expect(formatRuleMetrics({ maDistancePct: null })).toEqual([])
  expect(formatRuleMetrics({ maDistancePct: -0.01, maSlopePct: 0, stopDistancePct: 0 }))
    .toEqual(['距月線 0.0%', '月線斜率 0.00%／5 日', '停損距離 0.0%'])
})
const all = { maDistancePct: 4.67, maSlopePct: 6.72, stopDistancePct: -6.9 }
it('原因已含月線斜率或距月線時不重複', () => {
  expect(formatRuleMetrics({ ...all, reason: '月線斜率 6.72%，門檻 ≥ 0.50%，成立' }))
    .toEqual(['距月線 +4.7%', '停損距離 -6.9%'])
  expect(formatRuleMetrics({ ...all, reason: '收盤距月線 4.67%' }))
    .toEqual(['月線斜率 +6.72%／5 日', '停損距離 -6.9%'])
})
it('原因含停損距離或距觸價時不顯示停損距離', () => {
  expect(formatRuleMetrics({ ...all, reason: '收盤距觸價 0.9%' }))
    .toEqual(['距月線 +4.7%', '月線斜率 +6.72%／5 日'])
  expect(formatRuleMetrics({ ...all, reason: '進場｜停損距離 -3.4%（以觸價 26.88 計）' }))
    .toEqual(['距月線 +4.7%', '月線斜率 +6.72%／5 日'])
})
it('沒有原因時顯示全部指標', () => {
  expect(formatRuleMetrics(all)).toEqual(['距月線 +4.7%', '月線斜率 +6.72%／5 日', '停損距離 -6.9%'])
})
it('停損距離絕對值超過門檻才算大', () => {
  expect(isLargeStopDistance(-8.2, 10)).toBe(false)
  expect(isLargeStopDistance(-11, 10)).toBe(true)
  expect(isLargeStopDistance(7, 7)).toBe(false)
  expect(isLargeStopDistance(null, 7)).toBe(false)
  expect(isLargeStopDistance(undefined, 7)).toBe(false)
})
