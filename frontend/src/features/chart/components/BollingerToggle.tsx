interface BollingerToggleProps {
  visible: boolean
  onChange: (next: boolean) => void
}

export function BollingerToggle({ visible, onChange }: BollingerToggleProps) {
  return (
    <div className="ema-toggle">
      <label className="checkbox-row">
        <input type="checkbox" checked={visible} onChange={() => onChange(!visible)} />
        <span className="ema-toggle__swatch" style={{ background: '#e87ba4' }} />
        <span>布林通道</span>
      </label>
    </div>
  )
}
