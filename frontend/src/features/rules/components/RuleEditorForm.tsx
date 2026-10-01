import { useState, type FormEvent } from 'react'
import type { ConditionCatalogItem, LogicOperator, WatchRule } from '../types'

interface RuleEditorFormProps {
  conditionCatalog: ConditionCatalogItem[]
  onSubmit: (rule: Omit<WatchRule, 'id'>) => void
}

export function RuleEditorForm({ conditionCatalog, onSubmit }: RuleEditorFormProps) {
  const [name, setName] = useState('')
  const [logicOperator, setLogicOperator] = useState<LogicOperator>('AND')
  const [selectedConditionIds, setSelectedConditionIds] = useState<string[]>([])

  const toggleCondition = (conditionId: string) => {
    setSelectedConditionIds((prev) =>
      prev.includes(conditionId) ? prev.filter((id) => id !== conditionId) : [...prev, conditionId],
    )
  }

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault()
    if (!name || selectedConditionIds.length === 0) return

    onSubmit({
      name,
      logicOperator,
      isEnabled: true,
      // 各條件的實際參數(週期、倍數等)先固定給空物件，之後依condition_catalog的
      // param_schema動態產生對應輸入欄位。
      conditions: selectedConditionIds.map((conditionId) => ({ conditionId, params: {} })),
    })

    setName('')
    setLogicOperator('AND')
    setSelectedConditionIds([])
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
        <span>邏輯運算子</span>
        <select
          value={logicOperator}
          onChange={(e) => setLogicOperator(e.target.value as LogicOperator)}
        >
          <option value="AND">AND(全部條件都要成立)</option>
          <option value="OR">OR(任一條件成立即可)</option>
        </select>
      </label>

      <fieldset>
        <legend>選擇條件</legend>
        {conditionCatalog.map((condition) => (
          <label key={condition.id} className="checkbox-row">
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
        ))}
      </fieldset>

      <button className="button-primary" type="submit">
        新增規則
      </button>
    </form>
  )
}
