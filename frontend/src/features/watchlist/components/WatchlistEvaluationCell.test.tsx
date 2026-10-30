// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { apiClient } from '../../../api/client'
import { WatchlistEvaluationCell } from './WatchlistEvaluationCell'
import { RuleStateBadge } from '../../rules/components/RuleStateBadge'
import type { SavedEvaluation } from '../types'

afterEach(() => { cleanup(); vi.restoreAllMocks() })
beforeEach(() => { vi.spyOn(apiClient, 'get').mockResolvedValue({}) })
const result: SavedEvaluation = {
  itemId: 1,
  ruleId: 2,
  ruleName: '戰法二',
  state: 'EXIT',
  stale: false,
  evaluatedAt: '2026-10-29T10:00:00Z',
  expectedDataDate: '2026-10-29',
  marketDataStale: true,
  result: {
    ruleId: 2,
    ticker: '2330',
    isMet: false,
    logicOperator: 'AND',
    status: 'matched',
    dataDate: '2026-10-28',
    conditionResults: [],
    state: {
      state: 'EXIT',
      reason: '跌破月線',
      close: 188.5,
      triggerPrice: 190,
      distancePct: -0.8,
    },
  },
}
function show(results: SavedEvaluation[], client = new QueryClient()) {
  return render(
    <QueryClientProvider client={client}>
      <WatchlistEvaluationCell
        results={results}
        busy={false}
      />
    </QueryClientProvider>,
  )
}
it('shows Chinese badges, dated prices and stale market warnings', () => {
  const { container } = show([result])
  expect(screen.getByTitle('戰法二：出場')).toBeTruthy()
  expect(container.textContent).not.toContain('EXIT')
  expect(screen.getByText('行情過期')).toBeTruthy()
  expect(screen.getByText('行情 10/28').className).toBe('stale-notice')
  expect(screen.getByTitle('最後行情 2026-10-28，最近交易日 2026-10-29')).toBeTruthy()
  expect(container.textContent).toContain('現價 188.5（10/28）')
})
it('uses the latest result date and omits warnings for current market data', () => {
  show([
    { ...result, marketDataStale: false },
    {
      ...result,
      ruleId: 3,
      marketDataStale: false,
      result: { ...result.result, dataDate: '2026-10-29' },
    },
  ])
  expect(screen.getByText('行情 10/29')).toBeTruthy()
  expect(screen.queryByText('行情過期')).toBeNull()
})
it('allows a Chinese badge label override', () => {
  render(<RuleStateBadge ruleName="戰法二" state="STALE" label="行情過期" />)
  expect(screen.getByTitle('戰法二：行情過期').textContent).toBe('戰法二行情過期')
})

it('週頻結果顯示月 K 截止日期與更新說明', () => {
  const { container } = show([{
    ...result,
    evaluationFrequency: 'weekly',
    marketDataStale: false,
    result: { ...result.result, dataDate: '2026-10-22' },
  }])
  expect(screen.getByText('月 K：2026/10（計算至 10/22）')).toBeTruthy()
  expect(container.textContent).toContain('現價 188.5（月 K 計算至 10/22）')
  expect(screen.getAllByTitle('戰法三每週最後一個交易日收盤後更新')).toHaveLength(2)
  expect(screen.queryByText('行情過期')).toBeNull()
})

it('行情摘要優先使用日頻日期，即使週頻日期較新', () => {
  show([
    { ...result, evaluationFrequency: 'daily', marketDataStale: false },
    {
      ...result, ruleId: 3, evaluationFrequency: 'weekly', marketDataStale: false,
      result: { ...result.result, dataDate: '2026-10-30' },
    },
  ])
  expect(screen.getByText('行情 10/28')).toBeTruthy()
  expect(screen.queryByText('行情 10/30')).toBeNull()
})

it('顯示共用指標', () => {
  const { container } = show([{
    ...result,
    result: { ...result.result, state: {
      ...result.result.state!, maDistancePct: 0.9, maSlopePct: 0.64, stopDistancePct: -2.1,
    } },
  }])
  expect(container.textContent).toContain('距月線 +0.9%｜月線斜率 +0.64%／5 日｜停損距離 -2.1%')
})

it.each([[-8.2, false], [-11, true]])('進場時依設定門檻顯示停損距離大 %s', async (stop, shown) => {
  vi.spyOn(apiClient, 'get').mockResolvedValue({ largeStopDistancePct: 0.1 })
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  show([{
    ...result,
    state: 'ENTRY',
    result: { ...result.result, state: {
      ...result.result.state!, state: 'ENTRY', reason: '進場', stopDistancePct: stop,
      largeStopDistance: !shown,
    } },
  }], client)
  await waitFor(() => expect(client.getQueryData(['settings'])).toEqual({ largeStopDistancePct: 0.1 }))
  expect(screen.queryByText('停損距離大') !== null).toBe(shown)
  if (shown) expect(screen.getByText('停損距離大').className).toBe('status-badge status-warning')
  client.clear()
})

it('非進場狀態不顯示停損距離大', () => {
  show([{
    ...result,
    result: { ...result.result, state: { ...result.result.state!, stopDistancePct: -20 } },
  }])
  expect(screen.queryByText('停損距離大')).toBeNull()
})
