const number = (n: number | null) =>
  n === null ? '無資料' : n.toLocaleString('zh-TW', { maximumFractionDigits: 2 })
export const metricLabel = (key: string) => {
  const names: Record<string, string> = {
    'ma_rising.ma': '月線',
    'ma_rising.ma_prev': '5 日前月線',
    'ma_rising.slope': '月線變化',
    'ma_rising.slope_pct': '月線斜率',
    'ma_touch_rebound.close': '收盤價',
    'ma_touch_rebound.close_distance_pct': '距月線',
    'ma_touch_rebound.ma': '月線',
    'ma_touch_rebound.prev_close': '前日收盤',
    'ma_touch_rebound.prev_ma': '前日月線',
    'price_touch_ma.ma': '月線',
    'price_touch_ma.low': '最低價',
    'price_touch_ma.close': '收盤價',
    'price_touch_ma.distance': '最低價距月線',
    'close_below_ma_days.ma': '月線',
    'close_below_ma_days.close': '收盤價',
    'close_below_ma_days.below_days': '跌破天數',
    'close_below_ma_days.buffer': '跌破緩衝比例',
    'kd_high_death_cross.k': '月 K',
    'kd_high_death_cross.d': '月 D',
    'kd_high_death_cross.prev_k': '上月 K',
    'macd_negative_any.dif': '月 DIF',
    'macd_negative_any.signal': '月 MACD 訊號',
    'bollinger_mid_up.mid': '布林中軌',
    'bollinger_mid_up.upper': '布林上軌',
    'bollinger_mid_up.slope': '中軌變化',
    'kd_golden_cross.k': '月 K',
    'kd_golden_cross.d': '月 D',
    'macd_positive.dif': '月 DIF',
    'macd_positive.signal': '月 MACD 訊號',
    'macd_positive.histogram': '月 MACD 柱',
    'macd_histogram_rising.histogram': '本月柱狀體',
    'macd_histogram_rising.previous': '上月柱狀體',
    'ema_golden_cross.short': '短 EMA',
    'ema_golden_cross.long': '長 EMA',
    'volume_spike.ratio': '量比',
    'volume_spike.average': '均量',
  }
  if (names[key]) return names[key]
  return '其他指標'
}
export const isPercentMetric = (key: string) => /(?:_pct|distance)$/.test(key)
export function metricValue(key: string, value: number | null): string {
  if (value === null || !isPercentMetric(key)) return number(value)
  const rounded = Math.round(value * 100 * 100) / 100
  const normalized = Object.is(rounded, -0) ? 0 : rounded
  return `${normalized > 0 ? '+' : ''}${normalized.toFixed(2)}%`
}

const shownLabels = ['月線', '月線斜率', '距月線', '收盤價', '前日收盤']

export function pickIndicators(indicators: Record<string, number | null>) {
  const shown: { key: string; label: string; value: string }[] = []
  const hidden: typeof shown = []
  for (const [key, value] of Object.entries(indicators)) {
    const label = metricLabel(key)
    const indicator = { key, label, value: metricValue(key, value) }
    if (shownLabels.includes(label) && !shown.some((item) => item.label === label)) {
      shown.push(indicator)
    } else {
      hidden.push(indicator)
    }
  }
  shown.sort((a, b) => shownLabels.indexOf(a.label) - shownLabels.indexOf(b.label))
  return { shown, hidden }
}
