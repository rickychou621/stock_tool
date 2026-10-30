// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, expect, it, vi } from 'vitest'
import { apiClient } from '../../api/client'
import { BacktestPage } from './BacktestPage'

const clients: QueryClient[] = []
afterEach(() => {
  cleanup()
  clients.forEach((client) => client.clear())
  clients.length = 0
  vi.restoreAllMocks()
})

function setup(changed = true, running = false) {
  const metrics = {
    tradeCount: 6, winRate: 0.5, averageReturn: 0.1, compoundReturn: 0.5,
    maxDrawdown: null, maxDrawdownMedian: null, maxDrawdownMax: null,
    maxDrawdownSampleCount: 2, excessReturnMedian: 0.12,
    profitFactor: 2, noLosses: false, insufficientSample: true,
  }
  const performance = {
    ruleId: 1, ruleName: '戰法三', actualStart: '2023-10-30', actualEnd: '2026-10-22',
    metrics, grossMetrics: metrics, benchmarkBuyHoldReturn: 0.3,
  }
  vi.spyOn(apiClient, 'get').mockImplementation(async <T,>(path: string) => ({
    '/rules?limit=50': [{ id: 1, name: '戰法三', isEnabled: true }],
    '/backtests/latest': {
      task: { batchId: 'batch', status: running ? 'running' : 'succeeded',
        tickers: ['6213'], costSnapshot: null, total: 1, completed: 1,
        succeeded: 1, failed: 0, errors: [] },
      staleInfo: null,
      scopeDiff: changed ? { added: ['3059'], removed: ['6213'] } : null,
      overall: [{ ...performance, stockCount: 1, evaluationFrequency: 'weekly' }],
      stocks: [{ ...performance, id: 1, ticker: '6213', stockName: '聯茂' }],
    },
  }[path] as T))
  const post = vi.spyOn(apiClient, 'post').mockResolvedValue({})
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  clients.push(client)
  render(<QueryClientProvider client={client}><BacktestPage /></QueryClientProvider>)
  return post
}

it('清單變更顯示差異與移除標記，重新回測沿用執行 API', async () => {
  const post = setup()
  const warning = await screen.findByText('觀察清單已變更（新增 1 檔、移除 1 檔），結果可能不完整')
  expect(warning.parentElement?.title).toBe('新增：3059；移除：6213')
  expect(screen.getByRole('option', { name: '6213 聯茂（已移出觀察清單）' })).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: '重新回測' }))
  await waitFor(() => expect(post).toHaveBeenCalledWith('/backtests', { ruleIds: [1] }))
})

it('整體回撤樣本不足、超額報酬與週頻說明使用各自口徑', async () => {
  setup(false)
  expect(await screen.findByText('樣本不足（交易 ≥ 3 筆的股票只有 2 檔）')).toBeTruthy()
  expect(screen.getByText('每週最後一個交易日評估，結束日可能早於日頻戰法')).toBeTruthy()
  const tables = screen.getAllByRole('table')
  expect(within(tables[0]).getByText('+12.00%')).toBeTruthy()
  expect(within(tables[1]).getByText('+20.00%')).toBeTruthy()
  expect(screen.queryByRole('button', { name: '重新回測' })).toBeNull()
})

it('執行中不可由清單警示重複啟動', async () => {
  setup(true, true)
  const button = await screen.findByRole('button', { name: '重新回測' })
  expect((button as HTMLButtonElement).disabled).toBe(true)
})
