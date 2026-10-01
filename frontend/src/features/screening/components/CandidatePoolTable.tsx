import { Link } from 'react-router-dom'
import { AddToWatchlistButton } from '../../watchlist/components/AddToWatchlistButton'
import { getStockName } from '../../../lib/stockDirectory'
import type { CandidateStock } from '../types'

interface CandidatePoolTableProps {
  items: CandidateStock[]
}

export function CandidatePoolTable({ items }: CandidatePoolTableProps) {
  if (items.length === 0) {
    return <p className="muted">目前候選池是空的。</p>
  }

  return (
    <div className="table-scroll" role="region" aria-label="資料表，可左右捲動" tabIndex={0}>
      <table className="data-table">
        <thead>
          <tr>
            <th>股票代號</th>
            <th>股票名稱</th>
            <th>入選原因</th>
            <th>加入時間</th>
            <th>觀察</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr key={item.ticker}>
              <td>
                <Link to={`/chart?ticker=${item.ticker}`} state={{ from: '/candidates' }}>
                  {item.ticker}
                </Link>
              </td>
              <td>{getStockName(item.ticker)}</td>
              <td>{item.reason}</td>
              <td>{item.addedAt}</td>
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
