// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { WatchlistEvaluationCell } from './WatchlistEvaluationCell'
import { RuleStateBadge } from '../../rules/components/RuleStateBadge'
import type { SavedEvaluation } from '../types'

afterEach(cleanup)
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
function show(results: SavedEvaluation[]) {
  return render(
    <WatchlistEvaluationCell
      results={results}
      expected={1}
      disabled={false}
      busy={false}
      onEvaluate={vi.fn()}
    />,
  )
}
it('shows Chinese badges, dated prices and stale market warnings', () => {
  const { container } = show([result])
  expect(screen.getByText('戰法二：出場')).toBeTruthy()
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
  expect(screen.getByTitle('行情過期').textContent).toBe('戰法二：行情過期')
})
