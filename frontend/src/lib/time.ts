const taipeiFormatter = new Intl.DateTimeFormat('en-CA', {
  timeZone: 'Asia/Taipei', year: 'numeric', month: '2-digit', day: '2-digit',
  hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
})

export function parseUtcTime(value: string): Date {
  const text = value.trim()
  return new Date(/(?:Z|[+-]\d{2}:\d{2})$/i.test(text) ? text : `${text}Z`)
}

function parts(date: Date): Record<string, string> {
  return Object.fromEntries(taipeiFormatter.formatToParts(date).map(({ type, value }) => [type, value]))
}

export function formatTaipeiTime(value: string | null | undefined): string {
  if (!value?.trim()) return '—'
  const date = parseUtcTime(value)
  if (!Number.isFinite(date.getTime())) return '—'
  const p = parts(date)
  return `${p.year}/${p.month}/${p.day} ${p.hour}:${p.minute}`
}

export function daysSinceTaipei(value: string, now = new Date()): number {
  const date = parseUtcTime(value)
  if (!Number.isFinite(date.getTime()) || !Number.isFinite(now.getTime())) return NaN
  const calendarDay = (date: Date) => {
    const p = parts(date)
    return Date.UTC(Number(p.year), Number(p.month) - 1, Number(p.day))
  }
  return (calendarDay(now) - calendarDay(date)) / 86_400_000
}
