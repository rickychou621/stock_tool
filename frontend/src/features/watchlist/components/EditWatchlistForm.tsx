import { useState, type FormEvent } from 'react'
import type { WatchlistItem, WatchlistEdit } from '../types'
interface Props {
  item: WatchlistItem
  onSave: (id: number, values: WatchlistEdit) => Promise<void>
  onCancel: () => void
}
export function EditWatchlistForm({ item, onSave, onCancel }: Props) {
  const [price, setPrice] = useState(item.entryPrice?.toString() ?? '')
  const [date, setDate] = useState(item.entryDate ?? '')
  const [notes, setNotes] = useState(item.notes)
  const [sector, setSector] = useState(item.sector)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      await onSave(item.id, {
        entryPrice: price ? Number(price) : null,
        entryDate: date || null,
        notes,
        sector,
      })
      onCancel()
    } catch (e) {
      setError(e instanceof Error ? e.message : '儲存失敗，請重試。')
    } finally {
      setBusy(false)
    }
  }
  return (
    <form className="watchlist-editor" onSubmit={submit}>
      <h3>
        編輯 {item.ticker} {item.stockName}
      </h3>
      <div className="filter-bar">
        <label className="field">
          進場價
          <input
            autoFocus
            type="number"
            min="0"
            step="0.01"
            value={price}
            onChange={(e) => setPrice(e.target.value)}
          />
        </label>
        <label className="field">
          進場日
          <input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
        </label>
        <label className="field">
          族群分類
          <input
            maxLength={80}
            value={sector}
            onChange={(e) => setSector(e.target.value)}
            placeholder="例如：ABF 載板"
          />
        </label>
      </div>
      <label className="field">
        觀察筆記
        <textarea
          maxLength={5000}
          rows={3}
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
        />
      </label>
      <p className="muted">族群分類也會顯示在個股查詢頁。</p>
      <div className="evaluation-actions">
        <button className="button-primary" disabled={busy}>
          {busy ? '儲存中…' : '儲存'}
        </button>
        <button type="button" disabled={busy} onClick={onCancel}>
          取消
        </button>
      </div>
      {error && (
        <p role="alert" className="error-text">
          {error}
        </p>
      )}
    </form>
  )
}
