import type { RuleStateCode } from '../rules/state'

export interface CandidateStock {
  ticker: string
  reason: string
  addedAt: string
}

// 已真的觸發規則(AND/OR條件都成立)的股票，跟候選池(還在盯盤、尚未觸發)是不同階段。
export interface TodayMatchItem {
  state: RuleStateCode | null
  id: number
  ticker: string
  name: string
  ruleName: string
  triggeredAt: string
  priceAtTrigger: number | null
}

export interface ScanSummary {
  rulesEvaluated: number
  excluded: number
  excludedCategories: string[]
  stocksScanned: number
  newAlerts: number
  matches: ScanMatch[]
  issues: { ticker: string; ruleName: string; reason: string }[]
}

export interface CandidateRefreshSummary {
  stocksScanned: number
  added: number
  expired: number
  activeTotal: number
}

export interface ScanMatch {
  state: RuleStateCode
  id: number | null
  ticker: string
  name: string
  ruleName: string
  priceAtTrigger: number | null
  dataDate: string | null
  isNotified: boolean
  reason: string
  reasons: string[]
}
export interface NotificationSummary {
  sentIds: number[]
  skippedIds: number[]
  failedIds: number[]
}

export interface ScanJob {
  jobId: string
  status: 'running' | 'done' | 'failed'
  done: number
  total: number
  summary: ScanSummary | null
  error: string | null
}
