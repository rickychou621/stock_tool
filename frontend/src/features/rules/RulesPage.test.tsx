// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, expect, it, vi } from 'vitest'
import { apiClient } from '../../api/client'
import { RulesPage } from './RulesPage'

const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
afterEach(() => {
  cleanup()
  client.clear()
  vi.restoreAllMocks()
})
it('只展開一列，PUT 成功後關閉並使規則相關快取失效', async () => {
  const rules = [1, 2].map((id) => ({
    id,
    name: `戰法 ${id}`,
    logicOperator: 'AND',
    isEnabled: true,
    conditions: [{ conditionId: 'ma_rising', params: {}, role: 'premise' }],
  }))
  vi.spyOn(apiClient, 'get').mockImplementation(
    async <T,>(path: string) =>
      (path === '/conditions'
        ? [
            {
              id: 'ma_rising',
              name: '月線',
              paramSchema: { period: 'int' },
              originalDefaults: { period: 20 },
              defaultParams: { period: 20 },
              originalNotes: {},
            },
          ]
        : rules) as T,
  )
  const put = vi.spyOn(apiClient, 'put').mockResolvedValue(rules[1])
  const invalidate = vi.spyOn(client, 'invalidateQueries')
  render(
    <QueryClientProvider client={client}>
      <RulesPage />
    </QueryClientProvider>,
  )
  const edit = await screen.findAllByRole('button', { name: /^編輯 / })
  fireEvent.click(edit[0])
  fireEvent.click(edit[1])
  expect(screen.getAllByRole('button', { name: '儲存' })).toHaveLength(1)
  fireEvent.click(screen.getByRole('button', { name: '儲存' }))
  await waitFor(() => expect(screen.queryByRole('button', { name: '儲存' })).toBeNull())
  expect(put).toHaveBeenCalledWith('/rules/2', {
    name: '戰法 2',
    conditions: [{ conditionId: 'ma_rising', params: { period: 20 } }],
  })
  for (const key of ['rules', 'watchlist', 'saved-evaluations', 'rule-state', 'backtest-report']) {
    expect(invalidate).toHaveBeenCalledWith({ queryKey: [key] })
  }
  expect(invalidate).not.toHaveBeenCalledWith({ queryKey: ['conditions'] })
})

it.each([false, true])('刪除規則須確認，確認結果為 %s', async (confirmed) => {
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(confirmed)
  const remove = vi.spyOn(apiClient, 'delete').mockResolvedValue(undefined)
  vi.spyOn(apiClient, 'get').mockImplementation(async <T,>(path: string) =>
    (path === '/conditions' ? [] : [{
      id: 1, name: '戰法 1', logicOperator: 'AND', isEnabled: true, conditions: [],
    }]) as T,
  )
  render(<QueryClientProvider client={client}><RulesPage /></QueryClientProvider>)
  fireEvent.click(await screen.findByRole('button', { name: '刪除 戰法 1' }))
  expect(confirm).toHaveBeenCalledWith('確定要刪除規則「戰法 1」？')
  if (confirmed) {
    await waitFor(() => expect(remove).toHaveBeenCalledWith('/rules/1'))
    expect(remove).toHaveBeenCalledTimes(1)
  } else {
    expect(remove).not.toHaveBeenCalled()
  }
})
