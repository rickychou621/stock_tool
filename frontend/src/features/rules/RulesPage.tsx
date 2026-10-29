import { PageHeader } from '../../components/PageHeader'
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../../api/client'
import { RuleList } from './components/RuleList'
import { RuleEditorForm } from './components/RuleEditorForm'
import type { ConditionCatalogItem, RuleUpdate, WatchRule } from './types'

const LIST_LIMIT = 10

export function RulesPage() {
  const queryClient = useQueryClient()
  const [deleteError, setDeleteError] = useState<string | null>(null)

  const rulesQuery = useQuery({
    queryKey: ['rules'],
    queryFn: () => apiClient.get<WatchRule[]>(`/rules?limit=${LIST_LIMIT}`),
  })

  const conditionsQuery = useQuery({
    queryKey: ['conditions'],
    queryFn: () => apiClient.get<ConditionCatalogItem[]>('/conditions'),
  })

  const createMutation = useMutation({
    mutationFn: (newRule: Omit<WatchRule, 'id'>) => apiClient.post<WatchRule>('/rules', newRule),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['rules'] }),
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, payload }: { id: number; payload: RuleUpdate }) =>
      apiClient.put<WatchRule>(`/rules/${id}`, payload),
    onSuccess: async () => {
      await Promise.all(
        [
          'rules',
          'watchlist',
          'saved-evaluations',
          'rule-state',
          'backtest-report',
          'backtest-detail',
          'watchlist-schedule-latest',
        ].map((key) => queryClient.invalidateQueries({ queryKey: [key] })),
      )
    },
  })

  const toggleMutation = useMutation({
    mutationFn: (rule: WatchRule) =>
      apiClient.patch<WatchRule>(`/rules/${rule.id}/enabled?is_enabled=${!rule.isEnabled}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['rules'] }),
  })

  const deleteMutation = useMutation({
    mutationFn: (ruleId: number) => apiClient.delete<void>(`/rules/${ruleId}`),
    onSuccess: () => {
      setDeleteError(null)
      queryClient.invalidateQueries({ queryKey: ['rules'] })
    },
    onError: (error: unknown) => {
      setDeleteError(error instanceof Error ? error.message : '刪除失敗，請稍後再試。')
    },
  })

  return (
    <section>
      <PageHeader
        title="規則管理"
        description="組合評估條件，管理掃描時使用的戰法。"
        eyebrow="工作空間設定"
      />

      <p className="muted">
        戰法一（5 分 K 10/60 EMA）尚未支援：需要盤中 5 分 K 資料與大戶買賣力資料。
      </p>

      <div className="card">
        {(rulesQuery.isLoading || conditionsQuery.isLoading) && <p className="muted">讀取中...</p>}
        {(rulesQuery.isError || conditionsQuery.isError) && (
          <p className="error-text">讀取失敗，請確認 backend 是否運行中。</p>
        )}
        {deleteError && <p className="error-text">{deleteError}</p>}
        {rulesQuery.data && conditionsQuery.data && (
          <RuleList
            rules={rulesQuery.data}
            conditionCatalog={conditionsQuery.data}
            onToggleEnabled={(rule) => toggleMutation.mutate(rule)}
            onSave={(id, payload) => updateMutation.mutateAsync({ id, payload })}
            onDelete={(ruleId) => {
                const rule = rulesQuery.data?.find((rule) => rule.id === ruleId)
                if (rule && window.confirm(`確定要刪除規則「${rule.name}」？`)) {
                  deleteMutation.mutate(ruleId)
                }
              }}
          />
        )}
      </div>

      {conditionsQuery.data && (
        <RuleEditorForm
          conditionCatalog={conditionsQuery.data}
          onSubmit={(newRule) => createMutation.mutate(newRule)}
        />
      )}
    </section>
  )
}
