export interface PriceBar {
  date: string
  open: number
  high: number
  low: number
  close: number
  volume: number
}

// EMA/KD都是拿真實K棒在前端算出來的(見utils/indicators.ts)，不是後端回傳的欄位。
// MACD面板還沒實作，先不放進這個型別，避免顯示假數字。
export interface IndicatorSnapshot {
  ema10: number
  ema60: number
  kdK: number
  kdD: number
}

export interface TriggerHistoryItem {
  id: number
  ruleName: string
  triggeredAt: string
  priceAtTrigger: number | null
}
