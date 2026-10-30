// @vitest-environment jsdom
import { cleanup, render } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'
import { RuleStateLine } from './RuleStateBadge'

afterEach(cleanup)

it('狀態行不重複原因中已有的數字', () => {
  const { container } = render(
    <RuleStateLine
      dataDate="2026-10-30"
      state={{
        state: 'HOLD',
        reason: '月線斜率 6.72%，門檻 ≥ 0.50%，成立｜未回到月線後轉強（收盤距月線 4.67%，門檻 ≤ 3.00%）',
        triggerPrice: 290.5,
        close: 312,
        distancePct: 7.4,
        maDistancePct: 4.7,
        maSlopePct: 6.72,
        stopDistancePct: -6.9,
      }}
    />,
  )
  expect(container.textContent).toBe(
    '續抱：月線斜率 6.72%，門檻 ≥ 0.50%，成立｜未回到月線後轉強（收盤距月線 4.67%，門檻 ≤ 3.00%）（觸價 290.5，現價 312（10/30））｜停損距離 -6.9%',
  )
})
