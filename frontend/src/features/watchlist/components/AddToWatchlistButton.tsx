import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../../../api/client'
import type { WatchlistItem } from '../types'

export function AddToWatchlistButton({ ticker }: { ticker: string }) {
  const client = useQueryClient()
  const watchlist = useQuery({
    queryKey: ['watchlist'],
    queryFn: () => apiClient.get<WatchlistItem[]>('/watchlist?limit=500'),
  })
  const mutation = useMutation({
    mutationFn: () => apiClient.post('/watchlist', { ticker }),
    onSuccess: () => client.invalidateQueries({ queryKey: ['watchlist'] }),
  })
  const added = watchlist.data?.some((item) => item.ticker === ticker) || mutation.isSuccess
  return (
    <div>
      <button
        className="button-add"
        type="button"
        disabled={added || mutation.isPending || watchlist.isLoading}
        onClick={() => mutation.mutate()}
      >
        {added ? '已在觀察清單' : mutation.isPending ? '加入中…' : '加入觀察'}
      </button>
      {mutation.isError && <p className="error-text">{mutation.error.message}</p>}
    </div>
  )
}
