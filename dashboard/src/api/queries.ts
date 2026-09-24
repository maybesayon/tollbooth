import {
  keepPreviousData,
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query'
import type {
  CreatedKey,
  Credential,
  GroupBy,
  Interval,
  LedgerFilters,
  Provider,
  RequestPage,
  SpendReport,
  TimeseriesReport,
  VirtualKey,
} from './types'
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

export function useCredentials() {
  const api = useApi()
  return useQuery({
    queryKey: ['credentials'],
    queryFn: ({ signal }) => api<Credential[]>('/admin/credentials', { signal }),
  })
}

export function useKeys(includeRevoked = true) {
  const api = useApi()
  return useQuery({
    queryKey: ['keys', includeRevoked],
    queryFn: ({ signal }) =>
      api<VirtualKey[]>('/admin/keys', { params: { include_revoked: includeRevoked }, signal }),
  })
}

export function useCreateCredential() {
  const api = useApi()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: { name: string; provider: Provider; api_key: string }) =>
      api<Credential>('/admin/credentials', { method: 'POST', body }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['credentials'] }),
  })
}

export function useCreateKey() {
  const api = useApi()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: { name: string; team: string; credential_id: string }) =>
      api<CreatedKey>('/admin/keys', { method: 'POST', body }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['keys'] }),
  })
}

export function useRevokeKey() {
  const api = useApi()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (keyId: string) =>
      api<VirtualKey>(`/admin/keys/${encodeURIComponent(keyId)}/revoke`, { method: 'POST' }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['keys'] }),
  })
}

export function useRequestLog(filters: LedgerFilters, limit = 50) {
  const api = useApi()
  return useInfiniteQuery({
    queryKey: ['requests', filters, limit],
    queryFn: ({ pageParam, signal }) =>
      api<RequestPage>('/admin/requests', {
        params: { ...filters, limit, cursor: pageParam },
        signal,
      }),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor,
    placeholderData: keepPreviousData,
  })
}
