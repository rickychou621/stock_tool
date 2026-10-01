import { Link } from 'react-router-dom'
import { AddToWatchlistButton } from '../../watchlist/components/AddToWatchlistButton'
import { getStockName } from '../../../lib/stockDirectory'
import type { TodayMatchItem } from '../types'

interface TodayMatchesTableProps {
  items: TodayMatchItem[]
}

export function TodayMatchesTable({ items }: TodayMatchesTableProps) {
  if (items.length === 0) {
    return <p className="muted">今天目前還沒有股票觸發規則。</p>
  }

  return (
    <div className="table-scroll" role="region" aria-label="資料表，可左右捲動" tabIndex={0}>
      <table className="data-table">
        <thead>
          <tr>
            <th>股票代號</th>
            <th>股票名稱</th>
            <th>觸發規則</th>
            <th>觸發時間</th>
            <th>觸發價位</th>
            <th>觀察</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr key={item.id}>
              <td>
                <Link to={`/chart?ticker=${item.ticker}`} state={{ from: '/matches' }}>
                  {item.ticker}
                </Link>
              </td>
              <td>{getStockName(item.ticker)}</td>
              <td>{item.ruleName}</td>
              <td>{item.triggeredAt}</td>
              <td>{item.priceAtTrigger}</td>
              <td>
                <AddToWatchlistButton ticker={item.ticker} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
