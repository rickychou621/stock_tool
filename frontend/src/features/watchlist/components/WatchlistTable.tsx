import { Fragment, useState } from 'react'
import { Link } from 'react-router-dom'
import { getStockName } from '../../../lib/stockDirectory'
import { outcome, type SavedEvaluation, type WatchlistEdit, type WatchlistItem } from '../types'
import { WatchlistEvaluationCell } from './WatchlistEvaluationCell'
import { EditWatchlistForm } from './EditWatchlistForm'
interface Props {
  items: WatchlistItem[]
  evaluations: SavedEvaluation[]
  ruleIds: number[]
  disabled: boolean
  busyItem: number | null
  errors: Record<number, string>
  onEvaluate: (item: WatchlistItem) => void
  onRemove: (id: number) => void
  onSave: (id: number, values: WatchlistEdit) => Promise<void>
}
export function WatchlistTable({
  items,
  evaluations,
  ruleIds,
  disabled,
  busyItem,
  errors,
  onEvaluate,
  onRemove,
  onSave,
}: Props) {
  const [editing, setEditing] = useState<number | null>(null)
  if (!items.length)
    return <p className="muted">沒有符合目前篩選條件的股票，可調整篩選或新增觀察股票。</p>
  return (
    <div className="table-scroll" role="region" aria-label="觀察清單，可左右捲動" tabIndex={0}>
      <table className="data-table watchlist-table">
        <thead>
          <tr>
            <th>股票／族群</th>
            <th>戰法評估</th>
            <th>持股與筆記</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => {
            const results = evaluations.filter(
              (r) => r.itemId === item.id && ruleIds.includes(r.ruleId),
            )
            const status = errors[item.id] ? 'error' : outcome(results, ruleIds.length)
            return (
              <Fragment key={item.id}>
                <tr
                  className={`evaluation-row evaluation-row--${busyItem === item.id ? 'pending' : status}`}
                >
                  <td>
                    <Link
                      className="row-link"
                      to={`/chart?ticker=${item.ticker}`}
                      state={{ from: window.location.pathname + window.location.search }}
                    >
                      {item.ticker} {item.stockName || getStockName(item.ticker)}
                    </Link>
                    <span className="sector-label">{item.sector || '未分類'}</span>
                  </td>
                  <td>
                    <WatchlistEvaluationCell
                      results={results}
                      expected={ruleIds.length}
                      disabled={disabled}
                      busy={busyItem === item.id}
                      error={errors[item.id]}
                      onEvaluate={() => onEvaluate(item)}
                    />
                  </td>
                  <td>
                    <details>
                      <summary>查看持股與筆記</summary>
                      <p>
                        進場價：{item.entryPrice ?? '—'}
                        <br />
                        進場日：{item.entryDate ?? '—'}
                      </p>
                      <p className="watchlist-notes">{item.notes || '尚無筆記'}</p>
                    </details>
                  </td>
                  <td>
                    <div className="evaluation-actions">
                      <button
                        disabled={disabled}
                        onClick={() => setEditing(editing === item.id ? null : item.id)}
                      >
                        編輯
                      </button>
                      <button
                        className="button-danger"
                        disabled={disabled}
                        onClick={() => onRemove(item.id)}
                        aria-label={`移除觀察股票 ${item.ticker}`}
                      >
                        移除
                      </button>
                    </div>
                  </td>
                </tr>
                {editing === item.id && (
                  <tr>
                    <td colSpan={4}>
                      <EditWatchlistForm
                        key={item.id}
                        item={item}
                        onSave={onSave}
                        onCancel={() => setEditing(null)}
                      />
                    </td>
                  </tr>
                )}
              </Fragment>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
