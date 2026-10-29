// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import { apiClient } from '../../api/client'
import { SettingsPage } from './SettingsPage'

afterEach(() => { cleanup(); vi.restoreAllMocks() })

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
  fireEvent.click(screen.getByRole('button', { name: '儲存' }))
  await screen.findByText('已儲存')
  expect(put).toHaveBeenCalledWith('/settings/etf-exclusion', { categories: ['futures'] })
  fireEvent.click(screen.getByLabelText('期貨'))
  expect(screen.queryByText('已儲存')).toBeNull()
  put.mockRejectedValueOnce(new Error('失敗'))
  fireEvent.click(screen.getByRole('button', { name: '儲存' }))
  await screen.findByRole('alert')
  expect(put).toHaveBeenLastCalledWith('/settings/etf-exclusion', { categories: [] })
  client.clear()
})
