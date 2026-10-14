export interface ScanSettings {
  enabled: boolean
  ruleIds: number[]
  workers: number
  requestsPerMinute: number
}
export interface RuleSnapshot {
  id: number
  name: string
}
export interface Task {
  kind: string
  batchId: string
  source: string
  status: string
  startedAt: string
  finishedAt: string | null
  baseline: string | null
  rules: RuleSnapshot[]
  total: number
  processed: number
  succeeded: number
  failed: number
  insufficient: number
  warnings: string[]
}
export interface Tasks {
  scan: Task | null
  initialize: Task | null
}
export interface Summary {
  batchId: string
  source: string
  status: string
  finishedAt: string
  baseline: string
  rules: RuleSnapshot[]
  total: number
  succeeded: number
  failed: number
  insufficient: number
  normalCount: number
  abnormalCount: number
  warnings: string[]
}
export interface Candidate {
  id: number
  ticker: string
  stockName: string
  kind: string
  ruleId: number
  ruleName: string
  status: string
  statusReason: string | null
  reason: string
  indicators: Record<string, number>
  close: number
  priceDate: string
  volume: number
  turnover: number | null
  scannedAt: string
  olderQuote: boolean
}
export interface Page<T> {
  items: T[]
  total: number
  page: number
  pageSize: number
}
export interface ScanError {
  ticker: string | null
  ruleId: number | null
  status: string
  reason: string
}
