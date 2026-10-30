import { expect, it } from 'vitest'
import { getSyncHint } from './syncHint'

it('行情已更新時優先提示重新掃描', () => {
  expect(getSyncHint('2026-10-28', '2026-10-29', new Date('2026-10-30T01:00:00Z')))
    .toEqual({ className: 'status-warning', message: '行情已同步到 10/29，本次結果以 10/28 判定，請重新掃描。' })
})

it('台北平日收盤前提示尚未收盤', () => {
  expect(getSyncHint('2026-10-28', '2026-10-28', new Date('2026-10-29T05:29:59Z')))
    .toEqual({ className: 'muted', message: '今日尚未收盤，目前以 10/28 判定。' })
})

it('台北時間 13:30 起提示自動同步時間', () => {
  expect(getSyncHint('2026-10-29', '2026-10-29', new Date('2026-10-30T05:30:00Z')))
    .toEqual({ className: 'muted', message: '今日（10/30）收盤行情於 18:00 自動同步，目前以 10/29 判定。' })
})

it('基準日已是今天或缺值時不提示', () => {
  const now = new Date('2026-10-30T06:00:00Z')
  expect(getSyncHint('2026-10-30', '2026-10-30', now)).toBeNull()
  expect(getSyncHint(null, '2026-10-30', now)).toBeNull()
})

it.each(['2026-10-30T16:00:00Z', '2026-11-01T06:00:00Z'])('台北週末不提示等待同步：%s', (now) => {
  expect(getSyncHint('2026-10-30', '2026-10-30', new Date(now))).toBeNull()
})
