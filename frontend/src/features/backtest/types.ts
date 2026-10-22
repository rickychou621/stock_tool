export interface CostSnapshot {
  feeRate: number
  feeDiscount: number
  taxRateStock: number
  taxRateEtf: number
}
export interface Metrics {
  tradeCount: number
  winRate: number | null
  averageReturn: number | null
  compoundReturn: number | null
  maxDrawdown: number | null
  profitFactor: number | null
  noLosses: boolean
  insufficientSample: boolean
}
export interface Performance {
  ruleId: number
  ruleName: string
  actualStart: string
  actualEnd: string
  metrics: Metrics
  grossMetrics: Metrics
  averageExcessReturn: number | null
  benchmarkBuyHoldReturn: number | null
}
export interface StockPerformance extends Performance {
  batchId: string
  id: number
  ticker: string
  stockName: string
  stale: boolean
  needsRerun: boolean
  rerunReason?: string
  costSnapshot: CostSnapshot | null
  warnings: string[]
  benchmarkReason: string | null
  calculatedAt: string
  openCount: number
  unfilledCount: number
  skippedSessions: number
}
export interface Report {
  task: null | {
    costSnapshot: CostSnapshot | null
    batchId: string
    status: string
    startDate: string
    endDate: string
    total: number
    completed: number
    succeeded: number
    failed: number
    errors: { ticker: string | null; reason: string }[]
  }
  staleInfo: { reason: 'definition' | 'data'; changedAt: string | null; ruleIds: number[] } | null
  overall: (Performance & { stockCount: number; stale: boolean })[]
  stocks: StockPerformance[]
}
export interface Trade {
  entrySignalDate: string
  entryDate: string | null
  entryPrice: number | null
  exitSignalDate: string | null
  exitDate: string | null
  exitPrice: number | null
  status: 'closed' | 'open' | 'unfilled'
  returnRate: number | null
  grossReturnRate?: number | null
  netReturnRate?: number | null
  grossUnrealizedReturn?: number | null
  netUnrealizedReturn?: number | null
  benchmarkReturn?: number | null
  excessReturn?: number | null
  benchmarkReason?: string | null
  unrealizedReturn: number | null
  holdingDays: number | null
  valuationDate: string | null
  pendingSide: 'buy' | 'sell' | null
}
export interface Detail {
  batchId: string
  stale: boolean
  needsRerun: boolean
  rerunReason?: string
  costSnapshot: CostSnapshot | null
  warnings: string[]
  benchmarkReason: string | null
  priceBasisDate: string
  tradeTotal: number
  signalTotal: number
  trades: Trade[]
  signals: { date: string; state: string; isMet: boolean }[]
}
