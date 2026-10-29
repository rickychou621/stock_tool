// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'
import { RuleStateBadge } from './RuleStateBadge'
import { STATE_LABELS, type RuleStateCode } from '../state'

afterEach(cleanup)

it.each(Object.keys(STATE_LABELS) as RuleStateCode[])('%s 狀態包含圖示並保留文字', (state) => {
  const { container } = render(<RuleStateBadge ruleName="戰法" state={state} />)
  expect(container.querySelector('svg')).not.toBeNull()
  expect(screen.getByTitle(`戰法：${STATE_LABELS[state]}`)).toBeTruthy()
  expect(screen.getByText(STATE_LABELS[state]).querySelector('svg')).not.toBeNull()
})

it('行情過期覆寫使用時鐘圖示', () => {
  const { container } = render(<RuleStateBadge ruleName="戰法" state="ENTRY" label="行情過期" />)
  expect(container.querySelector('svg')?.getAttribute('data-icon')).toBe('clock')
  expect(screen.getByTitle('戰法：行情過期')).toBeTruthy()
})
