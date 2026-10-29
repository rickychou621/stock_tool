import { faSpinner, faStar } from '@fortawesome/free-solid-svg-icons'
import { IconButton } from '../../../components/IconButton'
import { faStar as faStarOutline } from '@fortawesome/free-regular-svg-icons'
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
      <IconButton
        className={added ? 'icon-button--added' : 'button-add'}
        icon={mutation.isPending ? faSpinner : added ? faStar : faStarOutline}
        spinning={mutation.isPending}
        label={added ? '已在觀察清單' : `加入觀察 ${ticker}`}
        type="button"
        disabled={added || mutation.isPending || watchlist.isLoading}
        onClick={() => mutation.mutate()}
      />
      {mutation.isError && <p className="error-text">{mutation.error.message}</p>}
    </div>
  )
}
