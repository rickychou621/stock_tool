import { formatTaipeiTime } from '../../lib/time'

export function getSyncHint(
  baselineDate: string | null | undefined,
  latestMarketDate: string | null | undefined,
  now: Date,
): { message: string; className: 'status-warning' | 'muted' } | null {
  if (!baselineDate) return null
  const short = (date: string) => date.slice(5).replace('-', '/')
  if (latestMarketDate && latestMarketDate > baselineDate) {
    return {
      message: `行情已同步到 ${short(latestMarketDate)}，本次結果以 ${short(baselineDate)} 判定，請重新掃描。`,
      className: 'status-warning',
    }
  }
  const [calendar, time] = formatTaipeiTime(now.toISOString()).split(' ')
  const today = calendar.replaceAll('/', '-')
  const weekday = new Date(`${today}T00:00:00Z`).getUTCDay()
  if (weekday === 0 || weekday === 6 || baselineDate >= today) return null
  return {
    message: time < '13:30'
      ? `今日尚未收盤，目前以 ${short(baselineDate)} 判定。`
      : `今日（${short(today)}）收盤行情於 18:00 自動同步，目前以 ${short(baselineDate)} 判定。`,
    className: 'muted',
  }
}
