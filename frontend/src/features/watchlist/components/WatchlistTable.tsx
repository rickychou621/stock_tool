import { faPenToSquare, faRotate, faTrashCan } from '@fortawesome/free-solid-svg-icons'
import { IconButton } from '../../../components/IconButton'
import { mostUrgent } from '../../rules/state'
import { Fragment, useState } from 'react'
import { Link } from 'react-router-dom'
import { getStockName } from '../../../lib/stockDirectory'
import { type SavedEvaluation, type WatchlistEdit, type WatchlistItem } from '../types'
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
            const status = mostUrgent(results.map((r) => r.state))
            return (
              <Fragment key={item.id}>
                <tr
                  className={`evaluation-row evaluation-row--${busyItem === item.id ? 'pending' : (status?.toLowerCase() ?? 'pending')}`}
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
                      busy={busyItem === item.id}
                      error={errors[item.id]}
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
                      <IconButton
                        type="button"
                        variant="secondary"
                        icon={faRotate}
                        label={`${results.length ? '重新評估' : '評估'} ${item.ticker}`}
                        spinning={busyItem === item.id}
                        disabled={disabled || !ruleIds.length}
                        onClick={() => onEvaluate(item)}
                      />
                      <IconButton
                        icon={faPenToSquare}
                        label={`編輯 ${item.ticker}`}
                        disabled={disabled}
                        onClick={() => setEditing(editing === item.id ? null : item.id)}
                      />
                      <IconButton
                        variant="danger"
                        icon={faTrashCan}
                        disabled={disabled}
                        onClick={() => onRemove(item.id)}
                        label={`移除觀察股票 ${item.ticker}`}
                      />
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
