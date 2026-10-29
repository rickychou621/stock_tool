// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { faRotate } from '@fortawesome/free-solid-svg-icons'
import { IconButton } from './IconButton'

afterEach(cleanup)

it('提供可存取名稱與提示，並傳遞按鈕屬性和點擊事件', () => {
  const onClick = vi.fn()
  const { rerender } = render(<IconButton icon={faRotate} label="評估 1303" onClick={onClick} />)
  const button = screen.getByRole('button', { name: '評估 1303' })
  expect(button.getAttribute('title')).toBe('評估 1303')
  expect(button.getAttribute('type')).toBe('button')
  fireEvent.click(button)
  expect(onClick).toHaveBeenCalledTimes(1)
  rerender(<IconButton icon={faRotate} label="評估 1303" onClick={onClick} disabled />)
  fireEvent.click(button)
  expect(onClick).toHaveBeenCalledTimes(1)
})

it('執行中使用 Font Awesome 旋轉動畫', () => {
  const { container, rerender } = render(<IconButton icon={faRotate} label="評估" spinning />)
  expect(container.querySelector('svg')?.classList.contains('fa-spin')).toBe(true)
  rerender(<IconButton icon={faRotate} label="評估" />)
  expect(container.querySelector('svg')?.classList.contains('fa-spin')).toBe(false)
})
