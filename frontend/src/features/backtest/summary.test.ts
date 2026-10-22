import { expect, it } from 'vitest'
import { summarizeRule } from './summary'
import type { StockPerformance } from './types'

function stock(winRate: number | null, overrides: Partial<StockPerformance> = {}): StockPerformance {
  const metrics = {
    tradeCount: 10, winRate, averageReturn: 0.1, compoundReturn: 0.2,
    maxDrawdown: 0.1, profitFactor: 2, noLosses: false, insufficientSample: false,
  }
  return {
    id: 1, ruleId: 1, ruleName: '戰法一', ticker: '2330', stockName: '台積電',
    batchId: 'batch-1', actualStart: '2023-10-18', actualEnd: '2026-10-16',
    metrics, grossMetrics: metrics, averageExcessReturn: 0.05,
    benchmarkBuyHoldReturn: 0.1, benchmarkReason: null,
    stale: false, needsRerun: false, costSnapshot: null, warnings: [],
    calculatedAt: '2026-10-16', openCount: 0, unfilledCount: 0, skippedSessions: 0,
    ...overrides,
  }
}

it('奇數取排序後的中間勝率，僅統計該戰法且包含需重跑的結果', () => {
  expect(summarizeRule([
    stock(0.9), stock(0.2, { needsRerun: true }), stock(0.6),
    stock(0.1, { ruleId: 2 }),
  ], 1)).toEqual({ stockCount: 3, beatBenchmarkCount: 3, medianWinRate: 0.6 })
})

it('偶數取中間兩個勝率的平均', () => {
  expect(summarizeRule([stock(0.9), stock(0.2), stock(0.7), stock(0.4)], 1)
    .medianWinRate).toBeCloseTo(0.55)
})

it('基準或淨複利為 null、平手及落後都不算贏過基準', () => {
  const missingReturn = stock(0.5)
  missingReturn.metrics.compoundReturn = null
  expect(summarizeRule([
    stock(0.5, { benchmarkBuyHoldReturn: null }), missingReturn,
    stock(0.5, { benchmarkBuyHoldReturn: 0.2 }),
    stock(0.5, { benchmarkBuyHoldReturn: 0.3 }), stock(0.5),
  ], 1).beatBenchmarkCount).toBe(1)
})

it('零交易與無勝率資料不納入中位數，但仍列入股票數', () => {
  const noTrades = stock(0)
  noTrades.metrics.tradeCount = 0
  expect(summarizeRule([noTrades, stock(null), stock(0.8)], 1))
    .toEqual({ stockCount: 3, beatBenchmarkCount: 3, medianWinRate: 0.8 })
})

it('沒有可用勝率或沒有該戰法股票時，中位數為 null', () => {
  const noTrades = stock(0)
  noTrades.metrics.tradeCount = 0
  expect(summarizeRule([noTrades, stock(null)], 1).medianWinRate).toBeNull()
  expect(summarizeRule([stock(0.5)], 2))
    .toEqual({ stockCount: 0, beatBenchmarkCount: 0, medianWinRate: null })
})
