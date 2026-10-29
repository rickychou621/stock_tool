// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import { apiClient } from '../../api/client'
import { WatchlistPage } from './WatchlistPage'
import type { SavedEvaluation, WatchlistItem } from './types'
import type { WatchRule } from '../rules/types'

const rules: WatchRule[] = [1, 2].map((id) => ({
  id,
  name: `戰法 ${id}`,
  logicOperator: 'AND',
  isEnabled: true,
  conditions: [],
}))
const items: WatchlistItem[] = [1, 2, 3, 4, 5].map((id) => ({
  id,
  ticker: `100${id}`,
  stockName: `股票 ${id}`,
  sector: '測試',
  entryPrice: null,
  entryDate: null,
  notes: '',
  isActive: true,
}))
const evaluations: SavedEvaluation[] = items.flatMap((item, index) =>
  rules.map((rule) => ({
    itemId: item.id,
    ruleId: rule.id,
    ruleName: rule.name,
    state:
      rule.id === 2 ? 'ENTRY' : (['EXIT', 'EXIT', 'ENTRY', 'NEAR_EXIT', 'HOLD'] as const)[index],
    evaluatedAt: '2026-10-26T10:00:00Z',
    stale: false,
    result: {
      ruleId: rule.id,
      ticker: item.ticker,
      isMet: true,
      logicOperator: 'AND',
      status: 'matched',
      dataDate: '2026-10-26',
      conditionResults: [],
    },
  })),
)
const completedRun = {
  batchId: 'batch-1',
  tradeDate: '2026-10-26',
  startedAt: '2026-10-26T10:00:00Z',
  finishedAt: '2026-10-26T10:05:00Z',
  status: 'succeeded',
  total: 5,
  succeeded: 5,
  failed: 0,
  errors: [] as { id: number; ticker: string; reason: string }[],
}
const clients: QueryClient[] = []
function setup(run: typeof completedRun | null = null, pending = false, failed = false, saved = evaluations, stocks = items) {
  const scroll = vi.fn()
  Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
    configurable: true,
    value: scroll,
  })
  vi.spyOn(apiClient, 'get').mockImplementation(async <T,>(path: string) => {
    if (path === '/watchlist/evaluations') {
      if (failed) throw new Error('讀取失敗')
      if (pending) return new Promise<T>(() => {})
    }
    return {
      '/watchlist?limit=500': stocks,
      '/rules?limit=50': rules,
      '/watchlist/evaluations': saved,
      '/watchlist-schedule/settings': { enabled: true, ruleIds: [1, 2] },
      '/watchlist-schedule/latest': run,
    }[path] as T
  })
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  clients.push(client)
  const view = render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <WatchlistPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return { ...view, scroll }
}
afterEach(() => {
  cleanup()
  clients.splice(0).forEach((client) => client.clear())
  vi.restoreAllMocks()
  delete (HTMLElement.prototype as Partial<HTMLElement>).scrollIntoView
})

it('摘要卡依股票與戰法計數，切換出場篩選並再次點擊恢復全部', async () => {
  const { scroll } = setup()
  const exit = await screen.findByRole('button', { name: /今日該出場 2 筆/ })
  expect(screen.getByRole('button', { name: /今日進場訊號 6 筆/ })).toBeTruthy()
  expect(screen.getByRole('button', { name: /接近觸價 1 筆/ })).toBeTruthy()
  const table = screen.getByRole('table')
  expect(
    within(table)
      .getAllByRole('link')
      .map((link) => link.textContent),
  ).toEqual(['1001 股票 1', '1002 股票 2', '1004 股票 4', '1003 股票 3', '1005 股票 5'])
  fireEvent.click(exit)
  expect(exit.getAttribute('aria-pressed')).toBe('true')
  expect(
    within(table)
      .getAllByRole('link')
      .map((link) => link.textContent),
  ).toEqual(['1001 股票 1', '1002 股票 2'])
  expect(scroll).toHaveBeenCalledWith({ behavior: 'smooth', block: 'start' })
  expect(scroll.mock.instances[0]).toBe(screen.getByLabelText('戰法狀態計數'))
  fireEvent.click(exit)
  expect(exit.getAttribute('aria-pressed')).toBe('false')
  expect(within(table).getAllByRole('link')).toHaveLength(5)
})

it.each([null, completedRun])('沒有錯誤時排程預設收合，仍可手動展開', async (run) => {
  setup(run)
  await screen.findByText('已啟用')
  const summary = screen.getByText('每日自動更新').closest('summary')!
  const details = summary.parentElement as HTMLDetailsElement
  expect(details.open).toBe(false)
  if (run) expect(within(summary).getByText(/最近一次：完成/)).toBeTruthy()
  else expect(within(summary).queryByText(/最近一次：/)).toBeNull()
  fireEvent.click(summary)
  expect(details.open).toBe(true)
})

it.each([
  { ...completedRun, status: 'failed' },
  {
    ...completedRun,
    status: 'partial_failure',
    errors: [{ id: 1, ticker: '1001', reason: '行情失敗' }],
  },
])('最近一次失敗或有錯誤時自動展開排程', async (run) => {
  setup(run)
  await waitFor(() =>
    expect((screen.getByText('每日自動更新').closest('details') as HTMLDetailsElement).open).toBe(
      true,
    ),
  )
})

it.each([false, true])('評估結果讀取中或失敗時摘要顯示破折號', async (failed) => {
  setup(null, !failed, failed)
  if (failed) await screen.findByRole('alert')
  for (const title of ['今日該出場', '今日進場訊號', '接近觸價']) {
    expect(screen.getByRole('button', { name: new RegExp(`${title} — 筆`) })).toBeTruthy()
  }
})

it('同一檔不同戰法的接近出場與出場各自計數並可篩選', async () => {
  setup(null, false, false, [
    { ...evaluations[0], state: 'NEAR_EXIT' },
    { ...evaluations[1], state: 'EXIT' },
  ], [{ ...items[0], ticker: '3711', stockName: '日月光投控' }])
  const nearExit = await screen.findByRole('button', { name: '接近出場 1' })
  expect(screen.getByRole('button', { name: '出場 1' })).toBeTruthy()
  expect(screen.getByText('依戰法計算，同一檔可重複')).toBeTruthy()
  fireEvent.click(nearExit)
  expect(within(screen.getByRole('table')).getByRole('link', { name: '3711 日月光投控' })).toBeTruthy()
})
