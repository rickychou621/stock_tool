import { useState } from 'react'
import { ETF_CATEGORY_LABELS } from './etfCategories'
import { Link } from 'react-router-dom'
import { PageHeader } from '../../components/PageHeader'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../../api/client'

interface SettingsSummary {
  screeningIntervalMinutes: number
  candidatePoolLimit: number
  telegramConfigured: boolean
  excludedEtfCategories: string[]
}

interface TestTelegramResult {
  success: boolean
  message: string
}

export function SettingsPage() {
  const queryClient = useQueryClient()
  const [selected, setSelected] = useState<string[] | null>(null)
  const { data, isLoading, isError } = useQuery({
    queryKey: ['settings'],
    queryFn: () => apiClient.get<SettingsSummary>('/settings'),
  })

  const categories = selected ?? data?.excludedEtfCategories ?? []
  const saveExclusion = useMutation({
    mutationFn: () => apiClient.put('/settings/etf-exclusion', { categories }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['settings'] }),
  })

  const testTelegram = useMutation({
    mutationFn: () => apiClient.post<TestTelegramResult>('/settings/test-telegram'),
  })

  return (
    <section>
      <PageHeader
        title="系統設定"
        description="查看篩選參數與通知設定，確認 Telegram 連線。"
        eyebrow="工作空間設定"
      />

      <div className="card">
        <h3>目前參數</h3>
        {isLoading && <p className="muted">讀取中...</p>}
        {isError && <p className="muted">設定讀取失敗，請稍後重新整理。</p>}
        {data && (
          <div className="stat-grid">
            <div className="stat-tile">
              <span className="stat-tile__label">候選池更新頻率（尚未啟用）</span>
              <span className="stat-tile__value">{data.screeningIntervalMinutes} 分鐘</span>
            </div>
            <div className="stat-tile">
              <span className="stat-tile__label">候選池上限</span>
              <span className="stat-tile__value">{data.candidatePoolLimit} 檔</span>
            </div>
            <div className="stat-tile">
              <span className="stat-tile__label">Telegram</span>
              <span className="stat-tile__value">
                {data.telegramConfigured ? '已設定' : '尚未設定'}
              </span>
            </div>
          </div>
        )}
        <p className="muted">
          每日自動更新請至<Link to="/">觀察清單</Link>設定；候選池定時更新尚未啟用。
        </p>
      </div>

      <div className="card">
        <h3>排除的 ETF 類別</h3>
        <p className="muted">勾選的類別不會出現在今日符合戰法清單與全市場掃描結果。</p>
        <div className="etf-exclusion-options">
          {Object.entries(ETF_CATEGORY_LABELS).map(([category, label]) => (
            <label key={category}>
              <input
                type="checkbox"
                checked={categories.includes(category)}
                disabled={!data || saveExclusion.isPending}
                onChange={(event) => {
                  saveExclusion.reset()
                  setSelected(
                    event.target.checked
                      ? [...categories, category]
                      : categories.filter((value) => value !== category),
                  )
                }}
              />
              {label}
            </label>
          ))}
        </div>
        <button
          className="button-primary"
          type="button"
          disabled={!data || saveExclusion.isPending}
          onClick={() => saveExclusion.mutate()}
        >
          {saveExclusion.isPending ? '儲存中...' : '儲存'}
        </button>
        {saveExclusion.isSuccess && (
          <p className="success-text" role="status">
            已儲存
          </p>
        )}
        {saveExclusion.isError && (
          <p className="error-text" role="alert">
            儲存失敗，請重試。
          </p>
        )}
      </div>

      <div className="card">
        <h3>Telegram 推播測試</h3>
        <p className="muted">發送一則測試訊息到已設定的 Telegram 聊天室，確認通知是否正常。</p>
        <button
          className="button-notify"
          type="button"
          onClick={() => testTelegram.mutate()}
          disabled={testTelegram.isPending}
        >
          {testTelegram.isPending ? '發送中...' : '發送測試訊息'}
        </button>

        {testTelegram.data && (
          <p className={testTelegram.data.success ? 'success-text' : 'error-text'}>
            {testTelegram.data.message}
          </p>
        )}
        {testTelegram.isError && <p className="error-text">測試訊息發送失敗，請稍後重試。</p>}
      </div>
    </section>
  )
}
