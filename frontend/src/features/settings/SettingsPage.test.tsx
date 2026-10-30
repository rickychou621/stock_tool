// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import { apiClient } from '../../api/client'
import { SettingsPage } from './SettingsPage'

afterEach(() => { cleanup(); vi.restoreAllMocks() })
const etfCard = () => within(screen.getByRole('heading', { name: '排除的 ETF 類別' }).closest('.card') as HTMLElement)

it('讀取排除類別、切換勾選並儲存', async () => {
  vi.spyOn(apiClient, 'get').mockResolvedValue({
    screeningIntervalMinutes: 5, candidatePoolLimit: 10, telegramConfigured: false,
    excludedEtfCategories: ['leveraged', 'inverse', 'bond', 'futures'],
  })
  const put = vi.spyOn(apiClient, 'put').mockResolvedValue({ categories: ['futures'] })
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={client}>
    <MemoryRouter><SettingsPage /></MemoryRouter>
  </QueryClientProvider>)
  await waitFor(() => expect((screen.getByLabelText('期貨') as HTMLInputElement).checked).toBe(true))
  for (const label of ['槓桿', '反向', '債券']) fireEvent.click(screen.getByLabelText(label))
  fireEvent.click(etfCard().getByRole('button', { name: '儲存' }))
  await etfCard().findByText('已儲存')
  expect(put).toHaveBeenCalledWith('/settings/etf-exclusion', { categories: ['futures'] })
  fireEvent.click(screen.getByLabelText('期貨'))
  expect(etfCard().queryByText('已儲存')).toBeNull()
  put.mockRejectedValueOnce(new Error('失敗'))
  fireEvent.click(etfCard().getByRole('button', { name: '儲存' }))
  await etfCard().findByRole('alert')
  expect(put).toHaveBeenLastCalledWith('/settings/etf-exclusion', { categories: [] })
  client.clear()
})

it('調整停損距離警示門檻並儲存', async () => {
  vi.spyOn(apiClient, 'get').mockResolvedValue({
    screeningIntervalMinutes: 5, candidatePoolLimit: 10, telegramConfigured: false,
    excludedEtfCategories: [], largeStopDistancePct: 0.07,
  })
  const put = vi.spyOn(apiClient, 'put').mockResolvedValue({ largeStopDistancePct: 0.08 })
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={client}>
    <MemoryRouter><SettingsPage /></MemoryRouter>
  </QueryClientProvider>)
  const card = within(screen.getByRole('heading', { name: '停損距離警示門檻' }).closest('.card') as HTMLElement)
  const input = card.getByLabelText('停損距離警示門檻（%）') as HTMLInputElement
  await waitFor(() => expect(input.value).toBe('7'))
  fireEvent.change(input, { target: { value: '8' } })
  fireEvent.click(card.getByRole('button', { name: '儲存' }))
  await card.findByText('已儲存')
  expect(put).toHaveBeenCalledWith('/settings/stop-distance', { largeStopDistancePct: 0.08 })
  client.clear()
})
