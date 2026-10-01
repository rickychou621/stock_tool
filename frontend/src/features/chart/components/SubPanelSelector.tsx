import type { SubPanelIndicator } from './StockChart'

interface SubPanelSelectorProps {
  value: SubPanelIndicator
  onChange: (next: SubPanelIndicator) => void
}

export function SubPanelSelector({ value, onChange }: SubPanelSelectorProps) {
  return (
    <label className="field">
      <span>副圖指標</span>
      <select value={value} onChange={(e) => onChange(e.target.value as SubPanelIndicator)}>
        <option value="kd">KD</option>
        <option value="macd">MACD</option>
      </select>
    </label>
  )
}
