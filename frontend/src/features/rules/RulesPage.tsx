import { PageHeader } from '../../components/PageHeader'
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../../api/client'
import { RuleList } from './components/RuleList'
import { RuleEditorForm } from './components/RuleEditorForm'
import type { ConditionCatalogItem, WatchRule } from './types'

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
            onDelete={(ruleId) => deleteMutation.mutate(ruleId)}
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
