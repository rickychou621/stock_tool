// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import { apiClient } from '../../api/client'
import { MarketScanPage } from './MarketScanPage'

afterEach(() => { cleanup(); vi.restoreAllMocks() })

it.each([
  [-0.021, undefined, false],
  [-0.114, undefined, true],
  [-0.082, 0.1, false],
  [-0.11, 0.1, true],
])('顯示共用指標且依停損距離警示 %s（門檻 %s）', async (stop, threshold, warned) => {
  vi.spyOn(apiClient, 'get').mockImplementation(async <T,>(path: string) => {
    if (path.startsWith('/market-scan/candidates?')) return {
      items: [{
        id: 1, ticker: '00646', stockName: '股票', kind: 'etf', ruleId: 2, ruleName: '戰法二',
        status: 'normal', reason: '進場原因', close: 100, priceDate: '2026-10-29',
        volume: 1000, turnover: null, scannedAt: '2026-10-29T10:00:00Z',
        indicators: {
          'ma_touch_rebound.close_distance_pct': 0.0092,
          'ma_rising.slope_pct': 0.0064,
          'protective_stop.stop_distance_pct': stop,
        },
      }], total: 1, page: 1, pageSize: 50,
    } as T
    if (path.startsWith('/market-scan/errors?')) return { items: [], total: 0 } as T
    if (path === '/market-scan/settings') return { enabled: false, ruleIds: [], workers: 5, requestsPerMinute: 4 } as T
    if (path === '/market-scan/tasks') return { scan: null, initialize: null } as T
    if (path === '/market-scan/summary') return null as T
    if (path === '/settings') return (threshold === undefined ? {} : { largeStopDistancePct: threshold }) as T
    return [] as T
  })
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={client}><MemoryRouter><MarketScanPage /></MemoryRouter></QueryClientProvider>)
  expect(await screen.findByText(`距月線 +0.9%｜月線斜率 +0.64%／5 日｜停損距離 ${(stop * 100).toFixed(1)}%`)).toBeTruthy()
  expect(screen.queryByText('距月線 +0.92%')).toBeNull()
  await waitFor(() => expect(client.getQueryState(['settings'])?.status).toBe('success'))
  expect(screen.queryByText('停損距離大') !== null).toBe(warned)
  client.clear()
})
