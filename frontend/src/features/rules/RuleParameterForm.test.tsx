// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { RuleList } from './components/RuleList'
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
    defaultParams: { period: 20, tolerance: 0.01, max_close_distance_pct: 0.03 },
    originalNotes: { max_close_distance_pct: '未給數值（要求回到月線附近）' },
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
    defaultParams: { short_period: 12 },
    originalNotes: {},
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
it('還原只改表單，儲存後才送系統預設', async () => {
  const save = vi.fn().mockResolvedValue(undefined)
  render(<RuleParameterForm rule={rule} catalog={catalog} onSave={save} onCancel={vi.fn()} />)
  fireEvent.click(screen.getByRole('button', { name: '還原為預設值' }))
  expect(save).not.toHaveBeenCalled()
  expect((screen.getByLabelText(/容許範圍/) as HTMLInputElement).value).toBe('1')
  expect(screen.queryByText('與原文不同')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '儲存' }))
  await waitFor(() => expect(save).toHaveBeenCalled())
  expect(save.mock.calls[0][1].conditions[0].params).toEqual({
    period: 20,
    tolerance: 0.01,
    max_close_distance_pct: 0.03,
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

const guardCatalog: ConditionCatalogItem[] = [
  catalog[0],
  {
    ...catalog[1],
    id: 'ma_rising',
    name: '月線上揚',
    paramSchema: { min_slope_pct: 'float' },
    originalDefaults: { min_slope_pct: null },
    defaultParams: { min_slope_pct: 0.005 },
    originalNotes: { min_slope_pct: '未給數值（要求有斜率）' },
  },
  {
    ...catalog[1],
    id: 'close_below_ma_days',
    name: '出場',
    paramSchema: { buffer: 'float' },
    originalDefaults: { buffer: 0 },
    defaultParams: { buffer: 0 },
    originalNotes: {
      buffer: '0% = 原文（收盤跌破月線即算）；2% = 容許小幅跌破，減少被洗出場，但出場較晚',
    },
  },
]
const guardRule: WatchRule = {
  ...rule,
  conditions: [
    {
      conditionId: 'ma_touch_rebound',
      role: 'entry',
      params: { period: 20, tolerance: 0.01, max_close_distance_pct: 0.03 },
    },
    { conditionId: 'ma_rising', role: 'premise', params: { min_slope_pct: 0.005 } },
  ],
}
it('戰法二顯示系統預設與原文要求，還原後保留兩項限制', () => {
  render(
    <RuleParameterForm
      rule={guardRule}
      catalog={guardCatalog}
      onSave={vi.fn()}
      onCancel={vi.fn()}
    />,
  )
  const distance = screen.getByLabelText(/收盤距月線上限/) as HTMLInputElement
  const slope = screen.getByLabelText(/月線斜率下限/) as HTMLInputElement
  expect(distance.value).toBe('3')
  expect(slope.value).toBe('0.5')
  expect(screen.getByText('原文：未給數值（要求回到月線附近）')).toBeTruthy()
  expect(screen.getByText('原文：未給數值（要求有斜率）')).toBeTruthy()
  expect(screen.getByText('預設：3%')).toBeTruthy()
  expect(screen.getByText('預設：0.5%')).toBeTruthy()
  expect(screen.queryByText('與原文不同')).toBeNull()
  fireEvent.change(distance, { target: { value: '8' } })
  fireEvent.change(slope, { target: { value: '' } })
  expect(screen.queryByText('與原文不同')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '還原為預設值' }))
  expect(distance.value).toBe('3')
  expect(slope.value).toBe('0.5')
})
it('出場緩衝保留 2% 與原文不同徽章及說明', () => {
  render(
    <RuleParameterForm
      rule={{
        ...rule,
        conditions: [
          { conditionId: 'close_below_ma_days', role: 'exit', params: { buffer: 0.02 } },
        ],
      }}
      catalog={guardCatalog}
      onSave={vi.fn()}
      onCancel={vi.fn()}
    />,
  )
  expect((screen.getByLabelText(/緩衝/) as HTMLInputElement).value).toBe('2')
  expect(screen.getByText('與原文不同')).toBeTruthy()
  expect(screen.getByText(guardCatalog[2].originalNotes.buffer)).toBeTruthy()
})
it('原文未給數值時，自訂或不限制都不視為偏離原文', () => {
  const item = guardCatalog[0]
  for (const value of [null, 0.03, 0.05]) {
    expect(
      differingParams({ max_close_distance_pct: value }, item.originalDefaults, item.originalNotes),
    ).toEqual([])
  }
  expect(
    formValues({ ...guardRule.conditions[0], params: { max_close_distance_pct: null } }, item)
      .max_close_distance_pct,
  ).toBe('')
})

it('列表只對出場緩衝顯示原文差異及 title', () => {
  render(
    <RuleList
      rules={[
        {
          ...guardRule,
          conditions: [
            ...guardRule.conditions,
            { conditionId: 'close_below_ma_days', role: 'exit', params: { buffer: 0.02 } },
          ],
        },
      ]}
      conditionCatalog={guardCatalog}
      onToggleEnabled={vi.fn()}
      onSave={vi.fn()}
      onDelete={vi.fn()}
    />,
  )
  const badges = screen.getAllByText('與原文不同')
  expect(badges).toHaveLength(1)
  expect(badges[0].title).toBe('緩衝：原文 0%，目前 2%')
})
