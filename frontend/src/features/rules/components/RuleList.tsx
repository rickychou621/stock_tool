import type { ConditionCatalogItem, RuleCondition, WatchRule } from '../types'

const ROLES = ['premise', 'entry', 'exit'] as const

const PARAM_LABELS: Record<string, (value: number) => string> = {
  period: (v) => `${v} 日均線`,
  slope_lookback: (v) => `比 ${v} 日前`,
  tolerance: (v) => `容許 ${pct(v)}`,
  days: (v) => `連續 ${v} 天`,
  buffer: (v) => `緩衝 ${pct(v)}`,
  threshold: (v) => `門檻 ${v}`,
  short_period: (v) => `短 ${v}`,
  long_period: (v) => `長 ${v}`,
}

function pct(value: number): string {
  return `${Number((value * 100).toFixed(2))}%`
}

function paramSummary(conditionId: string, params: RuleCondition['params']): string {
  return Object.entries(params)
    .map(([key, value]) => {
      if (key === 'period' && conditionId.startsWith('kd_')) return `KD ${String(value)} 日`
      return typeof value === 'number' && PARAM_LABELS[key]
        ? PARAM_LABELS[key](value)
        : `${key} ${String(value)}`
    })
    .join('・')
}

interface RuleListProps {
  rules: WatchRule[]
  conditionCatalog: ConditionCatalogItem[]
  onToggleEnabled: (rule: WatchRule) => void
  onDelete: (ruleId: number) => void
}

export function RuleList({ rules, conditionCatalog, onToggleEnabled, onDelete }: RuleListProps) {
  if (rules.length === 0) {
    return <p className="muted">目前沒有任何規則，新增一條開始監控。</p>
  }

  const conditionName = (conditionId: string): string =>
    conditionCatalog.find((c) => c.id === conditionId)?.name ?? conditionId

  return (
    <div className="table-scroll" role="region" aria-label="資料表，可左右捲動" tabIndex={0}>
      <table className="data-table">
        <thead>
          <tr>
            <th>規則名稱</th>
            <th>續抱</th>
            <th>進場</th>
            <th>出場</th>
            <th>啟用</th>
            <th aria-label="操作" />
          </tr>
        </thead>
        <tbody>
          {rules.map((rule) => (
            <tr key={rule.id}>
              <td>{rule.name}</td>
              {ROLES.map((role) => {
                const conditions = rule.conditions.filter((condition) => condition.role === role)
                const operator =
                  role === 'premise' ? rule.logicOperator : role === 'entry' ? 'AND' : 'OR'
                return (
                  <td key={role}>
                    {conditions.length === 0 && <span className="muted">—</span>}
                    {conditions.length > 1 && (
                      <small className="muted">{operator === 'AND' ? '全部成立' : '任一成立'}</small>
                    )}
                    {conditions.map((condition, index) => (
                      <div key={index} className="rule-condition">
                        <span>{conditionName(condition.conditionId)}</span>
                        {condition.conditionId === 'close_below_ma_days' &&
                          typeof condition.params.buffer === 'number' &&
                          condition.params.buffer > 0 && (
                            <span
                              className="status-badge status-warning"
                              title={`原文為收盤跌破月線（緩衝 0%），目前設定月線下方 ${pct(condition.params.buffer)}`}
                            >
                              與原文不同
                            </span>
                          )}
                        {Object.keys(condition.params).length > 0 && (
                          <small className="muted">{paramSummary(condition.conditionId, condition.params)}</small>
                        )}
                      </div>
                    ))}
                  </td>
                )
              })}
              <td>
                <input
                  type="checkbox"
                  aria-label={`啟用戰法：${rule.name}`}
                  checked={rule.isEnabled}
                  onChange={() => onToggleEnabled(rule)}
                />
              </td>
              <td>
                <button className="button-danger" type="button" onClick={() => onDelete(rule.id)}>
                  刪除
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
