import { useState, type FormEvent } from 'react'
import type { ConditionCatalogItem, LogicOperator, RuleCondition, WatchRule } from '../types'

interface RuleEditorFormProps {
  conditionCatalog: ConditionCatalogItem[]
  onSubmit: (rule: Omit<WatchRule, 'id'>) => void
}

export function RuleEditorForm({ conditionCatalog, onSubmit }: RuleEditorFormProps) {
  const [name, setName] = useState('')
  const [logicOperator, setLogicOperator] = useState<LogicOperator>('AND')
  const [selectedConditionIds, setSelectedConditionIds] = useState<string[]>([])

  const [conditionRoles, setConditionRoles] = useState<Record<string, RuleCondition['role']>>({})
  const [error, setError] = useState<string | null>(null)

  const toggleCondition = (conditionId: string) => {
    setSelectedConditionIds((prev) =>
      prev.includes(conditionId) ? prev.filter((id) => id !== conditionId) : [...prev, conditionId],
    )
  }

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault()
    if (!selectedConditionIds.some((id) => (conditionRoles[id] ?? 'premise') === 'premise')) {
      setError('至少要有 1 個續抱條件')
      return
    }
    if (!name) return
    setError(null)

    onSubmit({
      name,
      logicOperator,
      isEnabled: true,
      // 各條件的實際參數(週期、倍數等)先固定給空物件，之後依condition_catalog的
      // param_schema動態產生對應輸入欄位。
      conditions: selectedConditionIds.map((conditionId) => ({
        conditionId,
        params: {},
        role: conditionRoles[conditionId] ?? 'premise',
      })),
    })

    setName('')
    setLogicOperator('AND')
    setSelectedConditionIds([])
    setConditionRoles({})
  }

  return (
    <form className="card" onSubmit={handleSubmit}>
      <h3>新增規則</h3>

      <label className="field">
        <span>規則名稱</span>
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="例如：A+B組合監控"
        />
      </label>

      <label className="field">
        <span>續抱條件的組合方式</span>
        <select
          value={logicOperator}
          onChange={(e) => setLogicOperator(e.target.value as LogicOperator)}
        >
          <option value="AND">AND(全部條件都要成立)</option>
          <option value="OR">OR(任一條件成立即可)</option>
        </select>
      </label>

      <p className="muted">進場條件全部成立才算進場；出場條件任一成立就算出場。</p>

      <fieldset>
        <legend>選擇條件</legend>
        {conditionCatalog.map((condition) => (
          <div key={condition.id} className="checkbox-row">
            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={selectedConditionIds.includes(condition.id)}
                onChange={() => toggleCondition(condition.id)}
              />
              <span>
                {condition.name}
                <span className="muted">
                  {' '}
                  — {condition.description}({condition.requiredTimeframe})
                </span>
              </span>
            </label>
            {selectedConditionIds.includes(condition.id) && (
              <select
                aria-label={`${condition.name}的角色`}
                value={conditionRoles[condition.id] ?? 'premise'}
                onChange={(e) =>
                  setConditionRoles((prev) => ({
                    ...prev,
                    [condition.id]: e.target.value as RuleCondition['role'],
                  }))
                }
              >
                <option value="premise">續抱</option>
                <option value="entry">進場</option>
                <option value="exit">出場</option>
              </select>
            )}
          </div>
        ))}
      </fieldset>

      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}

      <button className="button-primary" type="submit">
        新增規則
      </button>
    </form>
  )
}
