import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faFloppyDisk, faRotateLeft, faXmark } from '@fortawesome/free-solid-svg-icons'
import { useState, type FormEvent } from 'react'
import type { ConditionCatalogItem, RuleUpdate, WatchRule } from '../types'
import {
  differingParams,
  displayValue,
  formValues,
  PARAM_LABELS,
  PERCENT_PARAMS,
  storedValue,
} from '../parameters'

interface Props {
  rule: WatchRule
  catalog: ConditionCatalogItem[]
  onSave: (id: number, payload: RuleUpdate) => Promise<unknown>
  onCancel: () => void
}
const ROLE_LABELS = { premise: '續抱', entry: '進場', exit: '出場' }
export function RuleParameterForm({ rule, catalog, onSave, onCancel }: Props) {
  const catalogs = rule.conditions.map((c) => catalog.find((item) => item.id === c.conditionId)!)
  const [name, setName] = useState(rule.name)
  const [values, setValues] = useState(() =>
    rule.conditions.map((c, i) => formValues(c, catalogs[i])),
  )
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  async function submit(event: FormEvent) {
    event.preventDefault()
    setSaving(true)
    setError(null)
    try {
      await onSave(rule.id, {
        name,
        conditions: rule.conditions.map((c, i) => ({
          conditionId: c.conditionId,
          params: Object.fromEntries(
            Object.entries(values[i]).flatMap(([key, value]) =>
              value === '' && catalogs[i].paramSchema[key] === 'int'
                ? []
                : [[key, storedValue(key, value)]],
            ),
          ),
        })),
      })
      onCancel()
    } catch (err) {
      setError(err instanceof Error ? err.message : '儲存失敗，請稍後再試。')
    } finally {
      setSaving(false)
    }
  }
  return (
    <form className="rule-parameter-form" onSubmit={submit}>
      <fieldset disabled={saving}>
        <label className="field">
          規則名稱
          <input required value={name} onChange={(e) => setName(e.target.value)} />
        </label>
        {rule.conditions.map((condition, index) => (
          <fieldset key={index}>
            <legend>
              {catalogs[index].name} · {ROLE_LABELS[condition.role]}
            </legend>
            {Object.entries(catalogs[index].paramSchema).map(([key, type]) => {
              const original = catalogs[index].originalDefaults[key]
              const optional = original === null || condition.params[key] == null
              const changed =
                differingParams(
                  { [key]: storedValue(key, values[index][key]) },
                  catalogs[index].originalDefaults,
                ).length > 0
              return (
                <label className="field" key={key}>
                  <span>
                    {PARAM_LABELS[key] ?? key}
                    {PERCENT_PARAMS.has(key) ? '（%）' : ''}
                  </span>
                  <input
                    type="number"
                    min={
                      key === 'period' ||
                      key === 'days' ||
                      key === 'slope_lookback' ||
                      key.endsWith('_period')
                        ? 1
                        : 0
                    }
                    step={type === 'int' ? 1 : 'any'}
                    required={!optional}
                    placeholder={optional ? '不限制' : undefined}
                    value={values[index][key]}
                    onChange={(e) =>
                      setValues((prev) =>
                        prev.map((v, i) => (i === index ? { ...v, [key]: e.target.value } : v)),
                      )
                    }
                  />
                  {original !== undefined && (
                    <small className="muted">原文：{displayValue(key, original)}</small>
                  )}
                  {changed && <span className="status-badge status-warning">與原文不同</span>}
                </label>
              )
            })}
          </fieldset>
        ))}
        {error && (
          <p className="error-text" role="alert">
            {error}
          </p>
        )}
        <div className="rule-actions">
          <button className="button-primary" type="submit">
            <FontAwesomeIcon icon={faFloppyDisk} />
            {saving ? '儲存中…' : '儲存'}
          </button>
          <button
            type="button"
            onClick={() =>
              setValues(rule.conditions.map((c, i) => formValues(c, catalogs[i], true)))
            }
          >
            <FontAwesomeIcon icon={faRotateLeft} />
            還原為原文預設
          </button>
          <button type="button" onClick={onCancel}>
            <FontAwesomeIcon icon={faXmark} />
            取消
          </button>
        </div>
      </fieldset>
    </form>
  )
}
