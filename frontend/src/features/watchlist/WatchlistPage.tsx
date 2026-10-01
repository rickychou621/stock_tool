import { useState } from 'react'
import { PageHeader } from '../../components/PageHeader'
import { Link, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../../api/client'
import type { WatchRule } from '../rules/types'
import { WatchlistTable } from './components/WatchlistTable'
import { AddWatchlistForm } from './components/AddWatchlistForm'
import {
  outcome,
  OUTCOME_LABELS,
  type Outcome,
  type SavedEvaluation,
  type WatchlistEdit,
  type WatchlistInput,
  type WatchlistItem,
} from './types'
interface Operation {
  busy: boolean
  busyItem: number | null
  progress: string
  errors: Record<number, string>
}
const EMPTY_OPERATION: Operation = { busy: false, busyItem: null, progress: '', errors: {} }
export function WatchlistPage() {
  const client = useQueryClient()
  const [params, setParams] = useSearchParams()
  const [filter, setFilter] = useState<Outcome | 'all'>('all')
  const [sector, setSector] = useState('all')
  const [sort, setSort] = useState('original')
  const operation = useQuery<Operation>({
    queryKey: ['watchlist-operation-v2'],
    queryFn: async () => EMPTY_OPERATION,
    enabled: false,
    initialData: EMPTY_OPERATION,
  })
  const updateOperation = (next: Partial<Operation>) =>
    client.setQueryData<Operation>(['watchlist-operation-v2'], (old) => ({
      ...EMPTY_OPERATION,
      ...old,
      ...next,
    }))
  const { busy, busyItem, progress, errors } = operation.data
  const watchlist = useQuery({
    queryKey: ['watchlist'],
    queryFn: () => apiClient.get<WatchlistItem[]>('/watchlist?limit=500'),
  })
  const rules = useQuery({
    queryKey: ['rules'],
    queryFn: () => apiClient.get<WatchRule[]>('/rules?limit=50'),
  })
  const saved = useQuery({
    queryKey: ['saved-evaluations'],
    queryFn: () => apiClient.get<SavedEvaluation[]>('/watchlist/evaluations'),
    refetchInterval: busy ? false : 30000,
  })
  const chosen = params.has('rules')
    ? params.get('rules')!.split(',').map(Number)
    : params.has('rule')
      ? [Number(params.get('rule'))]
      : (rules.data ?? []).filter((r) => r.isEnabled).map((r) => r.id)
  const ruleIds = (rules.data ?? []).filter((r) => chosen.includes(r.id)).map((r) => r.id)
  const items = watchlist.data ?? []
  const evaluations = saved.data ?? []
  const resultsFor = (item: WatchlistItem) =>
    evaluations.filter((r) => r.itemId === item.id && ruleIds.includes(r.ruleId))
  const statusFor = (item: WatchlistItem) =>
    errors[item.id] ? 'error' : outcome(resultsFor(item), ruleIds.length)
  const visible = items.filter(
    (i) =>
      (sector === 'all' || (i.sector || '未分類') === sector) &&
      (filter === 'all' || statusFor(i) === filter),
  )
  if (sort === 'passed')
    visible.sort((a, b) => Number(statusFor(b) === 'matched') - Number(statusFor(a) === 'matched'))
  if (sort === 'ticker') visible.sort((a, b) => a.ticker.localeCompare(b.ticker))
  async function evaluate(targets: WatchlistItem[]) {
    if (!ruleIds.length || client.getQueryData<Operation>(['watchlist-operation-v2'])?.busy) return
    updateOperation({ busy: true, errors: {} })
    let failures = 0
    try {
      for (const [index, item] of targets.entries()) {
        updateOperation({
          busyItem: item.id,
          progress: `${index + 1}／${targets.length}：${item.ticker} 更新行情並評估 ${ruleIds.length} 條戰法…`,
        })
        try {
          const result = await apiClient.post<SavedEvaluation[]>(`/watchlist/${item.id}/evaluate`, {
            ruleIds,
          })
          if (result.some((r) => r.result.status === 'error')) failures++
          client.setQueryData<SavedEvaluation[]>(['saved-evaluations'], (old) => [
            ...(old ?? []).filter((r) => !(r.itemId === item.id && ruleIds.includes(r.ruleId))),
            ...result,
          ])
          await client.invalidateQueries({ queryKey: ['chart', item.ticker] })
        } catch (e) {
          failures++
          client.setQueryData<Operation>(['watchlist-operation-v2'], (old) => ({
            ...old!,
            errors: {
              ...old!.errors,
              [item.id]: e instanceof Error ? e.message : '評估請求失敗，請重試。',
            },
          }))
        }
      }
      updateOperation({
        progress: `已處理 ${targets.length} 檔${failures ? `，其中 ${failures} 檔有失敗項目，請查看各股結果` : '，結果已保存'}。`,
      })
    } finally {
      updateOperation({ busy: false, busyItem: null })
      await client.invalidateQueries({ queryKey: ['saved-evaluations'] })
    }
  }
  const add = useMutation({
    mutationFn: (input: WatchlistInput) => apiClient.post('/watchlist', input),
    onSuccess: () => client.invalidateQueries({ queryKey: ['watchlist'] }),
  })
  const remove = useMutation({
    mutationFn: (id: number) => apiClient.delete(`/watchlist/${id}`),
    onSuccess: () => client.invalidateQueries({ queryKey: ['watchlist'] }),
  })
  async function save(id: number, values: WatchlistEdit) {
    await apiClient.patch(`/watchlist/${id}`, values)
    await Promise.all([
      client.invalidateQueries({ queryKey: ['watchlist'] }),
      client.invalidateQueries({ queryKey: ['stocks'] }),
      client.invalidateQueries({ queryKey: ['stock-profile'] }),
    ])
  }
  function toggle(id: number) {
    const next = ruleIds.includes(id) ? ruleIds.filter((x) => x !== id) : [...ruleIds, id]
    setParams({ rules: next.join(',') })
  }
  const complete = items.filter(
    (i) =>
      ruleIds.length > 0 &&
      resultsFor(i).length === ruleIds.length &&
      resultsFor(i).every((r) => !r.stale && ['matched', 'not_met'].includes(r.result.status)),
  ).length
  return (
    <section>
      <PageHeader title="觀察清單" description="先檢查追蹤股票，再從掃描結果發現新機會。" />
      <p className="muted">
        新增或進入清單不會自動評估。前往<Link to="/matches">今日符合戰法清單</Link>掃描新機會。
      </p>
      <div className="overview-grid">
        <div className="overview-tile">
          <span>追蹤股票</span>
          <strong>
            {watchlist.isLoading || watchlist.isError ? '—' : items.length}
            <small> 檔</small>
          </strong>
        </div>
        <div className="overview-tile">
          <span>選定戰法皆完成判斷</span>
          <strong>
            {saved.isLoading || saved.isError ? '—' : complete}
            <small> 檔</small>
          </strong>
        </div>
        <div className="overview-tile">
          <span>至少通過一條戰法</span>
          <strong>
            {saved.isLoading || saved.isError
              ? '—'
              : items.filter((i) => statusFor(i) === 'matched').length}
            <small> 檔</small>
          </strong>
        </div>
      </div>
      <div className="card">
        <fieldset disabled={busy}>
          <legend>評估戰法（可複選）</legend>
          <div className="rule-selection">
            {rules.data?.map((rule) => (
              <label className="checkbox-row" key={rule.id}>
                <input
                  type="checkbox"
                  checked={ruleIds.includes(rule.id)}
                  onChange={() => toggle(rule.id)}
                />
                {rule.name}
                {!rule.isEnabled ? '（掃描停用）' : ''}
              </label>
            ))}
          </div>
        </fieldset>
        {rules.isError && <p className="error-text">戰法讀取失敗，請重新整理。</p>}
        {rules.data?.length === 0 && <Link to="/rules">先建立戰法規則</Link>}
        <p className="muted">
          每檔股票只更新一次所需行情，再評估所選戰法並保存結果；不會發送
          Telegram。月K行情準備可能較久。
        </p>
        <button
          className="button-primary"
          disabled={busy || !ruleIds.length || !items.length}
          onClick={() => void evaluate(items)}
        >
          {busy ? '處理中…' : `評估全部 ${items.length} 檔 · ${ruleIds.length} 條戰法`}
        </button>
        {progress && (
          <p className="operation-status" role="status">
            {progress}
          </p>
        )}
        <div className="filter-bar">
          <label className="field">
            評估結果
            <select
              aria-label="評估結果"
              value={filter}
              onChange={(e) => setFilter(e.target.value as Outcome | 'all')}
            >
              <option value="all">全部結果</option>
              {Object.entries(OUTCOME_LABELS).map(([value, label]) => (
                <option key={value} value={value}>
                  {value === 'matched'
                    ? '至少通過一條'
                    : value === 'not_met'
                      ? '全部未通過'
                      : label}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            族群
            <select aria-label="族群" value={sector} onChange={(e) => setSector(e.target.value)}>
              <option value="all">全部族群</option>
              {[...new Set(items.map((i) => i.sector || '未分類'))].sort().map((s) => (
                <option key={s}>{s}</option>
              ))}
            </select>
          </label>
          <label className="field">
            排序
            <select aria-label="排序" value={sort} onChange={(e) => setSort(e.target.value)}>
              <option value="original">加入順序</option>
              <option value="passed">通過優先</option>
              <option value="ticker">股票代號</option>
            </select>
          </label>
          <button
            type="button"
            onClick={() => {
              setFilter('all')
              setSector('all')
              setSort('original')
            }}
          >
            清除篩選
          </button>
        </div>
        <p className="muted">
          顯示 {visible.length}／{items.length}{' '}
          檔。通過代表至少一條符合；全部未通過需所選戰法皆完成判斷。舊結果另列為需重新評估。
        </p>
        {(watchlist.isLoading || saved.isLoading) && <p role="status">讀取清單與上次結果…</p>}
        {(watchlist.isError || saved.isError) && (
          <p role="alert" className="error-text">
            清單或評估紀錄讀取失敗，請重新整理；目前顯示可能不完整。
          </p>
        )}
        {remove.isError && <p className="error-text">移除失敗，請重試。</p>}
        <WatchlistTable
          items={visible}
          evaluations={evaluations}
          ruleIds={ruleIds}
          disabled={busy || remove.isPending}
          busyItem={busyItem}
          errors={errors}
          onEvaluate={(item) => void evaluate([item])}
          onRemove={(id) => remove.mutate(id)}
          onSave={save}
        />
      </div>
      <AddWatchlistForm
        onSubmit={(input) => add.mutateAsync(input).then(() => undefined)}
        pending={add.isPending}
        error={add.error?.message}
      />
    </section>
  )
}
