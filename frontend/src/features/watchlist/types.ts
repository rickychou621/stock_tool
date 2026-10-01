import type { RuleEvaluationResult } from '../rules/types'

export interface WatchlistItem {
  id: number
  ticker: string
  entryPrice: number | null
  entryDate: string | null
  notes: string
  isActive: boolean
  stockName: string
  sector: string
}
export type WatchlistInput = Pick<WatchlistItem, 'ticker' | 'entryPrice' | 'entryDate' | 'notes'>
export type WatchlistEdit = Pick<WatchlistItem, 'entryPrice' | 'entryDate' | 'notes' | 'sector'>
export interface SavedEvaluation {
  itemId: number
  ruleId: number
  ruleName: string
  result: RuleEvaluationResult
  evaluatedAt: string
  stale: boolean
}
export type Outcome = 'matched' | 'not_met' | 'insufficient_data' | 'error' | 'pending' | 'stale'
export function outcome(results: SavedEvaluation[], expected: number): Outcome {
  if (results.some((r) => r.stale)) return 'stale'
  if (results.some((r) => r.result.status === 'matched')) return 'matched'
  if (results.some((r) => r.result.status === 'error')) return 'error'
  if (results.some((r) => r.result.status === 'insufficient_data')) return 'insufficient_data'
  if (!expected || results.length < expected) return 'pending'
  return 'not_met'
}
export const OUTCOME_LABELS: Record<Outcome, string> = {
  matched: '通過戰法',
  not_met: '未通過',
  insufficient_data: '資料不足',
  error: '評估失敗',
  pending: '尚未完成評估',
  stale: '需重新評估',
}
