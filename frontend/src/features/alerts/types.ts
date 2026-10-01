export interface AlertRecord {
  id: number
  ruleId: number
  ticker: string
  triggeredAt: string
  priceAtTrigger: number
  message: string
}
