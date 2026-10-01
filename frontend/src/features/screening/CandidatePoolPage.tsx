import { PageHeader } from '../../components/PageHeader'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../../api/client'
import { CandidatePoolTable } from './components/CandidatePoolTable'
import type { CandidateRefreshSummary, CandidateStock } from './types'

const LIST_LIMIT = 10

export function CandidatePoolPage() {
  const queryClient = useQueryClient()

  const candidatePool = useQuery({
    queryKey: ['screening-candidates'],
    queryFn: () => apiClient.get<CandidateStock[]>(`/screening/candidates?limit=${LIST_LIMIT}`),
  })

  // 這顆按鈕做的事情，就是之後排程要定時自動做的事情(兩階段篩選的第一階段)：
  // 用便宜的粗篩條件(均線多頭排列、爆量)掃全部股票，更新候選池名單。
  const refreshMutation = useMutation({
    mutationFn: () =>
      apiClient.post<CandidateRefreshSummary>(`/screening/candidates/refresh?limit=${LIST_LIMIT}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['screening-candidates'] }),
  })

  return (
    <section>
      <PageHeader
        title="候選池"
        description="用均線與成交量初步篩選，建立下一步研究的名單。"
        eyebrow="發現機會"
      />

      <div className="card">
        <h3>更新候選名單</h3>
        <p className="muted">
          手動觸發一次粗篩：用均線多頭排列、成交量放大條件掃描已有行情的股票，更新候選池。
          使用已儲存行情，不更新行情或發送通知；與戰法掃描分開執行。
        </p>
        <button
          className="button-primary"
          type="button"
          onClick={() => refreshMutation.mutate()}
          disabled={refreshMutation.isPending}
        >
          {refreshMutation.isPending ? '掃描中...' : '更新候選池'}
        </button>
        {refreshMutation.data && (
          <p className="success-text">
            掃描完成：檢查了 {refreshMutation.data.stocksScanned} 檔股票，新增{' '}
            {refreshMutation.data.added} 檔、汰除 {refreshMutation.data.expired} 檔，目前候選池共{' '}
            {refreshMutation.data.activeTotal} 檔。
          </p>
        )}
        {refreshMutation.isError && (
          <p className="error-text">掃描失敗，請確認 backend 是否運行中。</p>
        )}
      </div>

      <div className="card">
        <h3>目前候選池</h3>
        <p className="muted">通過粗篩的股票，不代表已符合戰法，也可能與今日符合清單重疊。</p>
        {candidatePool.isLoading && <p className="muted">讀取中...</p>}
        {candidatePool.isError && (
          <p className="error-text">讀取失敗，請確認 backend 是否運行中。</p>
        )}
        {candidatePool.data && <CandidatePoolTable items={candidatePool.data} />}
      </div>
    </section>
  )
}
