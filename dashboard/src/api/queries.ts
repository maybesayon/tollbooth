import {
  keepPreviousData,
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query'
import type {
  AlertChannel,
  ApiTokenInfo,
  AuditEvent,
  CreatedApiToken,
  CreatedUser,
  Role,
  User,
  Budget,
  BudgetAlert,
  BudgetInput,
  ChannelTestResult,
  ChannelType,
  CreatedAlertChannel,
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

export function useBudgets() {
  const api = useApi()
  return useQuery({
    queryKey: ['budgets'],
    queryFn: ({ signal }) => api<Budget[]>('/admin/budgets', { signal }),
    refetchInterval: 30_000,
  })
}

export function useSaveBudget() {
  const api = useApi()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, input }: { id: string | null; input: BudgetInput }) =>
      id === null
        ? api<Budget>('/admin/budgets', { method: 'POST', body: input })
        : api<Budget>(`/admin/budgets/${encodeURIComponent(id)}`, { method: 'PATCH', body: input }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['budgets'] }),
  })
}

export function useDeleteBudget() {
  const api = useApi()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) =>
      api<null>(`/admin/budgets/${encodeURIComponent(id)}`, { method: 'DELETE' }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['budgets'] }),
  })
}

export function useAlertChannels() {
  const api = useApi()
  return useQuery({
    queryKey: ['channels'],
    queryFn: ({ signal }) => api<AlertChannel[]>('/admin/channels', { signal }),
  })
}

export function useCreateAlertChannel() {
  const api = useApi()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: { name: string; type: ChannelType; url: string }) =>
      api<CreatedAlertChannel>('/admin/channels', { method: 'POST', body }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['channels'] }),
  })
}

export function useDeleteAlertChannel() {
  const api = useApi()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) =>
      api<null>(`/admin/channels/${encodeURIComponent(id)}`, { method: 'DELETE' }),
    onSuccess: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: ['channels'] }),
        queryClient.invalidateQueries({ queryKey: ['budgets'] }),
      ]),
  })
}

export function useTestAlertChannel() {
  const api = useApi()
  return useMutation({
    mutationFn: (id: string) =>
      api<ChannelTestResult>(`/admin/channels/${encodeURIComponent(id)}/test`, { method: 'POST' }),
  })
}

export function useAlerts(limit = 25) {
  const api = useApi()
  return useQuery({
    queryKey: ['alerts', limit],
    queryFn: ({ signal }) => api<BudgetAlert[]>('/admin/alerts', { params: { limit }, signal }),
    refetchInterval: 30_000,
  })
}

export function useApiTokens() {
  const api = useApi()
  return useQuery({
    queryKey: ['api-tokens'],
    queryFn: ({ signal }) => api<ApiTokenInfo[]>('/auth/tokens', { signal }),
  })
}

export function useCreateApiToken() {
  const api = useApi()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (name: string) =>
      api<CreatedApiToken>('/auth/tokens', { method: 'POST', body: { name } }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['api-tokens'] }),
  })
}

export function useDeleteApiToken() {
  const api = useApi()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) =>
      api<null>(`/auth/tokens/${encodeURIComponent(id)}`, { method: 'DELETE' }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['api-tokens'] }),
  })
}

export function useChangePassword() {
  const api = useApi()
  return useMutation({
    mutationFn: (body: { current_password: string; new_password: string }) =>
      api<null>('/auth/password', { method: 'POST', body }),
  })
}

export function useUsers() {
  const api = useApi()
  return useQuery({
    queryKey: ['users'],
    queryFn: ({ signal }) => api<User[]>('/admin/users', { signal }),
  })
}

export function useCreateUser() {
  const api = useApi()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: { email: string; name: string; role: Role }) =>
      api<CreatedUser>('/admin/users', { method: 'POST', body }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['users'] }),
  })
}

export function useUpdateUser() {
  const api = useApi()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...body }: { id: string; role?: Role; disabled?: boolean }) =>
      api<User>(`/admin/users/${encodeURIComponent(id)}`, { method: 'PATCH', body }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['users'] }),
  })
}

export function useResetPassword() {
  const api = useApi()
  return useMutation({
    mutationFn: (id: string) =>
      api<{ temporary_password: string }>(`/admin/users/${encodeURIComponent(id)}/reset-password`, {
        method: 'POST',
      }),
  })
}

export function useAuditLog(action: string, pageSize = 50) {
  const api = useApi()
  return useInfiniteQuery({
    queryKey: ['audit', action, pageSize],
    queryFn: ({ pageParam, signal }) =>
      api<AuditEvent[]>('/admin/audit', {
        params: { limit: pageSize, before: pageParam, action: action || undefined },
        signal,
      }),
    initialPageParam: null as string | null,
    getNextPageParam: (page) =>
      page.length === pageSize ? (page[page.length - 1]?.created_at ?? null) : null,
  })
}
