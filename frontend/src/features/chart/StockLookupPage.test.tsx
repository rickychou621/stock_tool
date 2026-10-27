// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import { apiClient } from '../../api/client'
import { StockLookupPage } from './StockLookupPage'

vi.mock('./components/StockChart', () => ({
  StockChart: (props: unknown) => <pre data-testid="chart">{JSON.stringify(props)}</pre>,
}))

const clients: QueryClient[] = []
const storageKey = 'stock-lookup:last-ticker'
function Location() {
  return <output data-testid="location">{useLocation().search}</output>
}
function setup(url = '/chart') {
  vi.spyOn(apiClient, 'get').mockImplementation(async <T,>(path: string) => {
    if (path === '/stocks?limit=20') return [{ ticker: '00400A', name: '預設股票' }] as T
    if (path === '/rules?limit=50') return [1, 2, 3].map((id) => ({
      id, name: `戰法${id}`, isEnabled: id !== 3, conditions: [], logicOperator: 'AND',
    })) as T
    if (path.startsWith('/rules/')) return { state: {
      state: 'HOLD', triggerPrice: path.startsWith('/rules/1/') ? 98 : null,
      close: 100, distancePct: null, reason: '測試',
    } } as T
    if (path.startsWith('/chart/')) return [{
      date: '2026-10-23', open: 100, high: 102, low: 99, close: 101, volume: 1000,
    }] as T
    if (path.startsWith('/alerts?')) return [{
      id: 1, ruleName: '戰法1', state: 'ENTRY', triggeredAt: '2026-10-22T17:00:00', priceAtTrigger: 100,
    }, {
      id: 2, ruleName: '舊紀錄', triggeredAt: '2026-10-22T05:00:00', priceAtTrigger: null,
    }] as T
    if (path.startsWith('/stocks/')) return { ticker: path.split('/').pop(), name: '測試股票', sector: '測試' } as T
    throw new Error(`未預期的請求：${path}`)
  })
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  clients.push(client)
  render(<QueryClientProvider client={client}>
    <MemoryRouter initialEntries={[url]}><StockLookupPage /><Location /></MemoryRouter>
  </QueryClientProvider>)
}
afterEach(() => {
  cleanup()
  clients.splice(0).forEach((client) => client.clear())
  vi.restoreAllMocks()
  localStorage.clear()
})

it('沒有 URL 股票時使用上次股票並同步網址', async () => {
  localStorage.setItem(storageKey, '2330')
  setup()
  await waitFor(() => expect(screen.getByTestId('location').textContent).toBe('?ticker=2330'))
  expect(apiClient.get).toHaveBeenCalledWith('/chart/2330?limit=120')
})

it('URL 股票優先並寫回儲存值', async () => {
  localStorage.setItem(storageKey, '2330')
  setup('/chart?ticker=2317')
  await screen.findByTestId('chart')
  expect(localStorage.getItem(storageKey)).toBe('2317')
  expect(apiClient.get).toHaveBeenCalledWith('/chart/2317?limit=120')
})

it('沒有記錄時使用清單第一檔', async () => {
  setup()
  await screen.findByTestId('chart')
  expect(localStorage.getItem(storageKey)).toBe('00400A')
})

it('localStorage 讀寫失敗時仍可查詢', async () => {
  vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('停用儲存') })
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('停用儲存') })
  setup()
  await screen.findByTestId('chart')
  expect(apiClient.get).toHaveBeenCalledWith('/chart/00400A?limit=120')
})

it('只傳有觸價的啟用戰法，歷史 UTC 時間換成台北日期', async () => {
  setup('/chart?ticker=2330')
  await waitFor(() => {
    const props = JSON.parse(screen.getByTestId('chart').textContent!)
    expect(props.priceLines).toEqual([{ price: 98, title: '戰法1 觸價', color: '#991b1b' }])
    expect(props.markers).toEqual([{ date: '2026-10-23', state: 'ENTRY', ruleName: '戰法1' }])
  })
  expect(screen.getByRole('heading', { name: '目前技術指標（2026/10/23，日K）' })).toBeTruthy()
})
