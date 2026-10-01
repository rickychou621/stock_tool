export type LogicOperator = 'AND' | 'OR'

export interface RuleCondition {
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

export interface ConditionCatalogItem {
  id: string
  name: string
  description: string
  requiredTimeframe: string
  updateFrequency: string
}

export interface ConditionEvaluation {
  conditionId: string
  isMet: boolean
  reason: string
  dataSufficient: boolean
}

export interface RuleEvaluationResult {
  ruleId: number
  ticker: string
  isMet: boolean
  logicOperator: LogicOperator
  status: 'matched' | 'not_met' | 'insufficient_data' | 'error'
  dataDate: string | null
  conditionResults: ConditionEvaluation[]
}
