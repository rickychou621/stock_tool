import { faPenToSquare, faTrashCan } from '@fortawesome/free-solid-svg-icons'
import { IconButton } from '../../../components/IconButton'
import { Fragment, useState } from 'react'
import { RuleParameterForm } from './RuleParameterForm'
import { differingParams, displayValue, PARAM_LABELS as FIELD_LABELS } from '../parameters'
import type { ConditionCatalogItem, RuleCondition, RuleUpdate, WatchRule } from '../types'

const ROLES = ['premise', 'entry', 'exit'] as const

const PARAM_LABELS: Record<string, (value: number) => string> = {
  period: (v) => `${v} 日均線`,
  slope_lookback: (v) => `比 ${v} 日前`,
  tolerance: (v) => `容許 ${pct(v)}`,
  days: (v) => `連續 ${v} 天`,
  buffer: (v) => `緩衝 ${pct(v)}`,
  min_slope_pct: (v) => `月線斜率下限 ${pct(v)}`,
  max_close_distance_pct: (v) => `收盤距月線上限 ${pct(v)}`,
  max_k_at_cross: (v) => `交叉時 K 值上限 ${v}`,
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
  onSave: (id: number, payload: RuleUpdate) => Promise<unknown>
  onDelete: (ruleId: number) => void
}

export function RuleList({
  rules,
  conditionCatalog,
  onToggleEnabled,
  onDelete,
  onSave,
}: RuleListProps) {
  const [editingId, setEditingId] = useState<number | null>(null)
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
            <Fragment key={rule.id}>
              <tr>
                <td>{rule.name}</td>
                {ROLES.map((role) => {
                  const conditions = rule.conditions.filter((condition) => condition.role === role)
                  const operator =
                    role === 'premise' ? rule.logicOperator : role === 'entry' ? 'AND' : 'OR'
                  return (
                    <td key={role}>
                      {conditions.length === 0 && <span className="muted">—</span>}
                      {conditions.length > 1 && (
                        <small className="muted">
                          {operator === 'AND' ? '全部成立' : '任一成立'}
                        </small>
                      )}
                      {conditions.map((condition, index) => (
                        <div key={index} className="rule-condition">
                          <span>{conditionName(condition.conditionId)}</span>
                          {differingParams(
                            condition.params,
                            conditionCatalog.find((c) => c.id === condition.conditionId)
                              ?.originalDefaults ?? {},
                            conditionCatalog.find((c) => c.id === condition.conditionId)
                              ?.originalNotes ?? {},
                          ).map((key) => (
                            <span
                              key={key}
                              className="status-badge status-warning"
                              title={`${FIELD_LABELS[key] ?? key}：原文 ${displayValue(key, conditionCatalog.find((c) => c.id === condition.conditionId)?.originalDefaults[key])}，目前 ${displayValue(key, condition.params[key])}`}
                            >
                              與原文不同
                            </span>
                          ))}
                          {Object.keys(condition.params).length > 0 && (
                            <small className="muted">
                              {paramSummary(condition.conditionId, condition.params)}
                            </small>
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
                  <div className="evaluation-actions">
                    <IconButton
                      type="button"
                      icon={faPenToSquare}
                      label={`編輯 ${rule.name}`}
                      aria-expanded={editingId === rule.id}
                      onClick={() => setEditingId(rule.id)}
                    />
                    <IconButton
                      variant="danger"
                      icon={faTrashCan}
                      label={`刪除 ${rule.name}`}
                      type="button"
                      onClick={() => onDelete(rule.id)}
                    />
                  </div>
                </td>
              </tr>
              {editingId === rule.id && (
                <tr>
                  <td colSpan={6}>
                    <RuleParameterForm
                      rule={rule}
                      catalog={conditionCatalog}
                      onSave={onSave}
                      onCancel={() => setEditingId(null)}
                    />
                  </td>
                </tr>
              )}
            </Fragment>
          ))}
        </tbody>
      </table>
    </div>
  )
}
