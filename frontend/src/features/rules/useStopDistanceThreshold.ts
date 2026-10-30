import { useQuery } from '@tanstack/react-query'
import { apiClient } from '../../api/client'

export function useStopDistanceThreshold(): number {
  const { data, isError } = useQuery({
    queryKey: ['settings'],
    queryFn: () => apiClient.get<{ largeStopDistancePct: number }>('/settings'),
  })
  const ratio = isError ? 0.07 : (data?.largeStopDistancePct ?? 0.07)
  return Number((ratio * 100).toFixed(4))
}
