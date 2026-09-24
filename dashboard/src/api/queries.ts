import { keepPreviousData, useQuery } from '@tanstack/react-query'
import type { GroupBy, Interval, LedgerFilters, SpendReport, TimeseriesReport } from './types'
import { useApi } from './useApi'

export function useSpend(groupBy: GroupBy, filters: LedgerFilters) {
  const api = useApi()
  return useQuery({
    queryKey: ['spend', groupBy, filters],
    queryFn: ({ signal }) =>
      api<SpendReport>('/admin/spend', { params: { group_by: groupBy, ...filters }, signal }),
    placeholderData: keepPreviousData,
  })
}

export function useTimeseries(
  interval: Interval,
  groupBy: GroupBy | null,
  filters: LedgerFilters & { start: string; end: string },
) {
  const api = useApi()
  return useQuery({
    queryKey: ['timeseries', interval, groupBy, filters],
    queryFn: ({ signal }) =>
      api<TimeseriesReport>('/admin/spend/timeseries', {
        params: { interval, group_by: groupBy, ...filters },
        signal,
      }),
    placeholderData: keepPreviousData,
  })
}
