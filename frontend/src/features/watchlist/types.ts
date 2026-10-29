import type { RuleStateCode } from '../rules/state'
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
  state: RuleStateCode
  itemId: number
  ruleId: number
  ruleName: string
  result: RuleEvaluationResult
  evaluatedAt: string
  expectedDataDate?: string | null
  marketDataStale?: boolean
  stale: boolean
}
