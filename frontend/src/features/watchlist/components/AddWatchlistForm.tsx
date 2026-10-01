import { useState, type FormEvent } from 'react'
import type { WatchlistInput } from '../types'

interface AddWatchlistFormProps {
  onSubmit: (item: WatchlistInput) => Promise<void>
  pending: boolean
  error?: string
}

export function AddWatchlistForm({ onSubmit, pending, error }: AddWatchlistFormProps) {
  const [ticker, setTicker] = useState('')
  const [entryPrice, setEntryPrice] = useState('')
  const [entryDate, setEntryDate] = useState('')
  const [notes, setNotes] = useState('')

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    if (!ticker) return

    try {
      await onSubmit({
        ticker: ticker.trim(),
        entryPrice: entryPrice ? Number(entryPrice) : null,
        entryDate: entryDate || null,
        notes,
      })

      setTicker('')
      setEntryPrice('')
      setEntryDate('')
      setNotes('')
    } catch {
      /* Parent keeps the error and input for retry. */
    }
  }

  return (
    <form className="card add-watchlist-form" onSubmit={handleSubmit}>
      <h3>新增觀察股票</h3>
      <p className="muted form-intro">輸入股票代號即可追蹤，其餘欄位為選填。新增後可手動評估。</p>

      <label className="field">
        <span>股票代號</span>
        <input
          required
          value={ticker}
          onChange={(e) => setTicker(e.target.value)}
          placeholder="例如：2330"
        />
      </label>

      <label className="field">
        <span>進場價(選填)</span>
        <input
          type="number"
          step="0.01"
          value={entryPrice}
          onChange={(e) => setEntryPrice(e.target.value)}
        />
      </label>

      <label className="field">
        <span>進場日(選填)</span>
        <input type="date" value={entryDate} onChange={(e) => setEntryDate(e.target.value)} />
      </label>

      <label className="field">
        <span>備註(選填)</span>
        <input value={notes} onChange={(e) => setNotes(e.target.value)} />
      </label>

      <button className="button-add" type="submit" disabled={pending}>
        {pending ? '新增中…' : '加入觀察清單'}
      </button>
      {error && (
        <p role="alert" className="error-text">
          {error}
        </p>
      )}
    </form>
  )
}
