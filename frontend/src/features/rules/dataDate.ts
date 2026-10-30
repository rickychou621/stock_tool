export const WEEKLY_DATA_DATE_TITLE = '戰法三每週最後一個交易日收盤後更新'

export function formatDataDate(
  dataDate: string | null | undefined,
  frequency = 'daily',
  dailyFormat: 'YYYY-MM-DD' | 'MM/DD' = 'YYYY-MM-DD',
) {
  if (!dataDate) return '無資料'
  const shortDate = dataDate.slice(5).replace('-', '/')
  if (frequency === 'weekly') {
    return `月 K：${dataDate.slice(0, 7).replace('-', '/')}（計算至 ${shortDate}）`
  }
  return dailyFormat === 'MM/DD' ? shortDate : dataDate
}
