// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import { apiClient } from '../../api/client'
import { ScreeningPage } from './ScreeningPage'
import type { ScanJob, ScanSummary } from './types'

const summary: ScanSummary = {
  baselineDate: '2026-10-28', finishedAt: '2026-10-29T06:05:00Z',
  rulesEvaluated: 1, stocksScanned: 2, newAlerts: 1, excluded: 0, excludedCategories: [], issues: [],
  matches: [{
    id: 1, ticker: '2330', name: '台積電', ruleName: '戰法', state: 'ENTRY',
    priceAtTrigger: 100, dataDate: '2026-10-22', isNotified: false,
    reason: '符合', reasons: ['符合'],
  }],
}

function setup(initial: ScanJob | null) {
  let job = initial
  vi.spyOn(apiClient, 'get').mockImplementation(async <T,>(path: string) =>
    (path === '/screening/run/latest' ? job : []) as T,
  )
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const mount = () => render(
    <QueryClientProvider client={client}>
      <MemoryRouter><ScreeningPage /></MemoryRouter>
    </QueryClientProvider>,
  )
  const view = mount()
  return { client, view, mount, setJob: (next: ScanJob) => { job = next } }
}

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

it('接回進行中的掃描，完成後顯示結果，重查與重新掛載不覆蓋通知狀態', async () => {
  const running: ScanJob = {
    jobId: 'job-1', status: 'running', done: 1, total: 2, summary: null, error: null,
  }
  const { client, view, mount, setJob } = setup(running)
  const button = await screen.findByRole('button', { name: '掃描中… 1/2' })
  expect((button as HTMLButtonElement).disabled).toBe(true)
  expect((screen.getByRole('button', { name: /通知 Telegram/ }) as HTMLButtonElement).disabled)
    .toBe(true)
  setJob({ ...running, status: 'done', done: 2, summary })
  await screen.findByText('本次掃描結果', {}, { timeout: 3000 })
  vi.spyOn(apiClient, 'post').mockResolvedValue({ sentIds: [1], skippedIds: [], failedIds: [] })
  fireEvent.click(screen.getByRole('button', { name: '通知 Telegram（1 檔）' }))
  await screen.findByText('已通知')
  await act(() => client.invalidateQueries({ queryKey: ['scan-job'] }))
  expect(client.getQueryData<ScanSummary>(['latest-scan'])?.matches[0].isNotified).toBe(true)
  view.unmount()
  mount()
  await screen.findByText('已通知')
  expect(client.getQueryData<ScanSummary>(['latest-scan'])?.matches[0].isNotified).toBe(true)
  client.clear()
})

it('啟動工作後顯示初始進度，背景失敗時顯示原因', async () => {
  const { client, setJob } = setup(null)
  await waitFor(() => expect(apiClient.get).toHaveBeenCalledWith('/screening/run/latest'))
  const running: ScanJob = {
    jobId: 'job-2', status: 'running', done: 0, total: 0, summary: null, error: null,
  }
  vi.spyOn(apiClient, 'post').mockImplementation(async <T,>() => {
    setJob(running)
    return { jobId: running.jobId } as T
  })
  fireEvent.click(screen.getByRole('button', { name: '立即掃描' }))
  await screen.findByRole('button', { name: '掃描中…' })
  setJob({ ...running, status: 'failed', error: 'ValueError: 無法評估' })
  await screen.findByText('掃描失敗：ValueError: 無法評估', {}, { timeout: 3000 })
  expect((screen.getByRole('button', { name: '立即掃描' }) as HTMLButtonElement).disabled)
    .toBe(false)
  client.clear()
})

it('顯示重複啟動時後端回傳的錯誤訊息', async () => {
  const { client } = setup(null)
  vi.spyOn(apiClient, 'post').mockRejectedValue(
    Object.assign(new Error('已有掃描進行中，請等待完成。'), { status: 409 }),
  )
  fireEvent.click(screen.getByRole('button', { name: '立即掃描' }))
  await screen.findByText('已有掃描進行中，請等待完成。')
  client.clear()
})

it('行情過期可篩選且不通知，排除文字依實際類別顯示', async () => {
  const { client } = setup({
    jobId: 'stale', status: 'done', done: 1, total: 1, error: null,
    summary: {
      ...summary, excluded: 3, excludedCategories: ['futures', 'bond'],
      matches: [{ ...summary.matches[0], id: null, state: 'STALE', reason: '行情過期原因' }],
    },
  })
  const filter = await screen.findByRole('button', { name: '行情過期 1' })
  expect(filter.getAttribute('aria-pressed')).toBe('false')
  expect(screen.queryByText('行情過期原因')).toBeNull()
  expect(screen.getByRole('button', { name: '進場 0' })).toBeTruthy()
  expect((screen.getByRole('button', { name: '通知 Telegram（0 檔）' }) as HTMLButtonElement).disabled)
    .toBe(true)
  expect(screen.getByText(/已排除 3 檔債券／期貨ETF/)).toBeTruthy()
  fireEvent.click(filter)
  expect(screen.getByText('戰法：行情過期')).toBeTruthy()
  expect(screen.getByText('行情過期原因')).toBeTruthy()
  client.clear()
})

it('隱藏出場卡片與篩選，顯示掃描基準與範圍說明', async () => {
  const { client } = setup({
    jobId: 'exit', status: 'done', done: 2, total: 2, error: null,
    summary: { ...summary, matches: [
      ...summary.matches,
      { ...summary.matches[0], id: null, ticker: '3711', state: 'EXIT' },
    ] },
  })
  await screen.findByText('本次掃描結果')
  expect(screen.queryByRole('button', { name: /^出場 / })).toBeNull()
  expect(screen.queryByText('出場訊號')).toBeNull()
  expect(screen.queryByRole('link', { name: /3711/ })).toBeNull()
  expect(screen.getByRole('link', { name: /2330/ })).toBeTruthy()
  expect(screen.getByText('基準日 2026-10-28・掃描時間 10/29 14:05')).toBeTruthy()
  expect(screen.getByText(/本頁只檢查已同步行情的 2 檔/)).toBeTruthy()
  expect(screen.getByText('篩選數字依戰法計算（筆），同一檔可重複')).toBeTruthy()
  client.clear()
})

it('掃描日期與時間缺值顯示破折號', async () => {
  const { client } = setup({
    jobId: 'missing-time', status: 'done', done: 2, total: 2, error: null,
    summary: { ...summary, baselineDate: null, finishedAt: null },
  })
  await screen.findByText('基準日 —・掃描時間 —')
  client.clear()
})
