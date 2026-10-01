import type { IndicatorSnapshot } from '../types'

interface IndicatorSummaryProps {
  indicators: IndicatorSnapshot
}

export function IndicatorSummary({ indicators }: IndicatorSummaryProps) {
  const items = [
    { label: 'EMA10', value: indicators.ema10 },
    { label: 'EMA60', value: indicators.ema60 },
    { label: 'KD K值', value: indicators.kdK },
    { label: 'KD D值', value: indicators.kdD },
  ]

  return (
    <div className="stat-grid">
      {items.map((item) => (
        <div className="stat-tile" key={item.label}>
          <span className="stat-tile__label">{item.label}</span>
          <span className="stat-tile__value">{item.value}</span>
        </div>
      ))}
    </div>
  )
}
