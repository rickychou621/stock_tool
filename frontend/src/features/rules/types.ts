import type { RuleStateDetail } from './state'

export type LogicOperator = 'AND' | 'OR'

export interface RuleCondition {
  role: 'premise' | 'entry' | 'exit'
  conditionId: string
  params: Record<string, unknown>
}

export interface WatchRule {
  id: number
  name: string
  logicOperator: LogicOperator
  isEnabled: boolean
  conditions: RuleCondition[]
}

export interface RuleUpdate {
  name: string
  conditions: { conditionId: string; params: Record<string, number | null> }[]
}

export interface ConditionCatalogItem {
  paramSchema: Record<string, 'int' | 'float'>
  defaultParams: Record<string, number | null>
  originalNotes: Record<string, string>
  originalDefaults: Record<string, number | null>
  id: string
  name: string
  description: string
  requiredTimeframe: string
  updateFrequency: string
}

export interface ConditionEvaluation {
  role?: 'premise' | 'entry' | 'exit'
  conditionId: string
  isMet: boolean
  reason: string
  dataSufficient: boolean
  upperBandStatus?: 'touched' | 'breakout' | null
}

export interface RuleEvaluationResult {
  evaluationFrequency?: string
  state?: RuleStateDetail | null
  premiseMet?: boolean
  entryTriggered?: boolean | null
  exitTriggered?: boolean | null
  protectiveStop?: {
    close: number | null
    price: number
    ma: number
    tick: number
    buffer?: number
    ticks: number
  } | null
  ruleId: number
  ticker: string
  isMet: boolean
  logicOperator: LogicOperator
  status: 'matched' | 'not_met' | 'insufficient_data' | 'error'
  dataDate: string | null
  conditionResults: ConditionEvaluation[]
}
