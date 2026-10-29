// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { RuleParameterForm } from './components/RuleParameterForm'
import { differingParams, formValues, storedValue } from './parameters'
import type { ConditionCatalogItem, WatchRule } from './types'

const catalog: ConditionCatalogItem[] = [
  {
    id: 'ma_touch_rebound',
    name: '回踩',
    description: '',
    requiredTimeframe: 'daily',
    updateFrequency: 'daily',
    paramSchema: { period: 'int', tolerance: 'float', max_close_distance_pct: 'float' },
    originalDefaults: { period: 20, tolerance: 0.01, max_close_distance_pct: null },
  },
  {
    id: 'macd_positive',
    name: 'MACD',
    description: '',
    requiredTimeframe: 'daily',
    updateFrequency: 'daily',
    paramSchema: {},
    originalDefaults: { short_period: 12 },
  },
]
const rule: WatchRule = {
  id: 1,
  name: '戰法',
  logicOperator: 'AND',
  isEnabled: true,
  conditions: [
    {
      conditionId: 'ma_touch_rebound',
      role: 'premise',
      params: { period: 30, tolerance: 0.02, max_close_distance_pct: 0.05 },
    },
    { conditionId: 'macd_positive', role: 'entry', params: {} },
  ],
}
afterEach(cleanup)
it('缺省參數視為原文，數字與 null 差異逐項比較', () => {
  const defaults = catalog[0].originalDefaults
  expect(differingParams({}, defaults)).toEqual([])
  expect(
    differingParams({ period: 20.0, tolerance: 0.01, max_close_distance_pct: null }, defaults),
  ).toEqual([])
  expect(differingParams({ period: 30, max_close_distance_pct: 0 }, defaults)).toEqual([
    'period',
    'max_close_distance_pct',
  ])
  expect(storedValue('tolerance', '2.5')).toBe(0.025)
  expect(storedValue('max_close_distance_pct', '')).toBeNull()
  expect(formValues(rule.conditions[1], catalog[1], true)).toEqual({})
})
it('百分比換算送出，空白限制傳 null，保留條件順序', async () => {
  const save = vi.fn().mockResolvedValue(undefined)
  const cancel = vi.fn()
  render(<RuleParameterForm rule={rule} catalog={catalog} onSave={save} onCancel={cancel} />)
  fireEvent.change(screen.getByLabelText(/容許範圍/), { target: { value: '2.5' } })
  fireEvent.change(screen.getByLabelText(/收盤距月線上限/), { target: { value: '' } })
  fireEvent.click(screen.getByRole('button', { name: '儲存' }))
  await waitFor(() => expect(cancel).toHaveBeenCalled())
  expect(save).toHaveBeenCalledWith(1, {
    name: '戰法',
    conditions: [
      {
        conditionId: 'ma_touch_rebound',
        params: { period: 30, tolerance: 0.025, max_close_distance_pct: null },
      },
      { conditionId: 'macd_positive', params: {} },
    ],
  })
})
it('還原只改表單，儲存後才送原文預設', async () => {
  const save = vi.fn().mockResolvedValue(undefined)
  render(<RuleParameterForm rule={rule} catalog={catalog} onSave={save} onCancel={vi.fn()} />)
  fireEvent.click(screen.getByRole('button', { name: '還原為原文預設' }))
  expect(save).not.toHaveBeenCalled()
  expect((screen.getByLabelText(/容許範圍/) as HTMLInputElement).value).toBe('1')
  expect(screen.queryByText('與原文不同')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '儲存' }))
  await waitFor(() => expect(save).toHaveBeenCalled())
  expect(save.mock.calls[0][1].conditions[0].params).toEqual({
    period: 20,
    tolerance: 0.01,
    max_close_distance_pct: null,
  })
})
it('儲存失敗顯示 detail 並保留編輯內容', async () => {
  const cancel = vi.fn()
  render(
    <RuleParameterForm
      rule={rule}
      catalog={catalog}
      onSave={vi
        .fn()
        .mockRejectedValue(new Error('條件 ma_touch_rebound 的參數 period：必須是整數'))}
      onCancel={cancel}
    />,
  )
  fireEvent.click(screen.getByRole('button', { name: '儲存' }))
  expect((await screen.findByRole('alert')).textContent).toContain('period：必須是整數')
  expect(cancel).not.toHaveBeenCalled()
})
