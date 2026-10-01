import type { TriggerHistoryItem } from '../types'

interface TriggerHistoryListProps {
  items: TriggerHistoryItem[]
}

export function TriggerHistoryList({ items }: TriggerHistoryListProps) {
  if (items.length === 0) {
    return <p className="muted">目前沒有觸發紀錄。</p>
  }

  return (
    <div className="table-scroll" role="region" aria-label="資料表，可左右捲動" tabIndex={0}>
      <table className="data-table">
        <thead>
          <tr>
            <th>觸發規則</th>
            <th>觸發時間</th>
            <th>觸發價位</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr key={item.id}>
              <td>{item.ruleName}</td>
              <td>{item.triggeredAt}</td>
              <td>{item.priceAtTrigger}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
