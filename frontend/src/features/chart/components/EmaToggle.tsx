import type { EmaVisibility } from './StockChart'

const EMA_LABELS: Record<keyof EmaVisibility, string> = {
  ema10: '10EMA',
  ema20: '20EMA',
  ema60: '60EMA',
}

const EMA_SWATCH_COLORS: Record<keyof EmaVisibility, string> = {
  ema10: '#2a78d6',
  ema20: '#eb6834',
  ema60: '#4a3aa7',
}

interface EmaToggleProps {
  visibility: EmaVisibility
  onChange: (next: EmaVisibility) => void
}

export function EmaToggle({ visibility, onChange }: EmaToggleProps) {
  const keys = Object.keys(EMA_LABELS) as Array<keyof EmaVisibility>

  return (
    <div className="ema-toggle">
      {keys.map((key) => (
        <label key={key} className="checkbox-row">
          <input
            type="checkbox"
            checked={visibility[key]}
            onChange={() => onChange({ ...visibility, [key]: !visibility[key] })}
          />
          <span className="ema-toggle__swatch" style={{ background: EMA_SWATCH_COLORS[key] }} />
          <span>{EMA_LABELS[key]}</span>
        </label>
      ))}
    </div>
  )
}
