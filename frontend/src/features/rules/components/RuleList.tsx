import type { ConditionCatalogItem, WatchRule } from '../types'

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
            <th>條件組合</th>
            <th>啟用</th>
            <th aria-label="操作" />
          </tr>
        </thead>
        <tbody>
          {rules.map((rule) => (
            <tr key={rule.id}>
              <td>{rule.name}</td>
              <td>
                {rule.conditions
                  .map((c) => conditionName(c.conditionId))
                  .join(` ${rule.logicOperator} `)}
              </td>
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
