import { describe, expect, it } from 'vitest'
import { formatDataDate } from './dataDate'

describe('formatDataDate', () => {
  it('preserves the caller’s daily date format', () => {
    expect(formatDataDate('2026-10-28')).toBe('2026-10-28')
    expect(formatDataDate('2026-10-28', 'daily', 'MM/DD')).toBe('10/28')
  })
  it('labels monthly candles with the weekly cutoff', () => {
    expect(formatDataDate('2026-10-22', 'weekly')).toBe('月 K：2026/10（計算至 10/22）')
    expect(formatDataDate('2026-10-22', 'weekly', 'MM/DD')).toBe('月 K：2026/10（計算至 10/22）')
  })
  it('handles missing dates', () => {
    expect(formatDataDate(null, 'weekly')).toBe('無資料')
    expect(formatDataDate(undefined)).toBe('無資料')
  })
})
