import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useMemo, type ReactNode } from 'react'
import { ApiError, apiRequest } from '../api/client'
import type { Me, Role } from '../api/types'
import { AuthContext } from './AuthContext'
import { includes } from './roles'

const ME = ['me'] as const

async function fetchMe(): Promise<Me | null> {
  try {
    return await apiRequest<Me>('/auth/me')
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) return null
    throw error
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()
  const me = useQuery({ queryKey: ME, queryFn: fetchMe, staleTime: Infinity, retry: false })

  const signedIn = useCallback(
    (next: Me) => {
      queryClient.removeQueries({ predicate: (q) => q.queryKey[0] !== ME[0] })
      queryClient.setQueryData(ME, next)
    },
    [queryClient],
  )

  const expired = useCallback(() => {
    queryClient.removeQueries({ predicate: (q) => q.queryKey[0] !== ME[0] })
    queryClient.setQueryData(ME, null)
  }, [queryClient])

  const signOut = useCallback(async () => {
    try {
      await apiRequest('/auth/logout', { method: 'POST' })
    } catch {
      // Signing out locally is what matters; the session may already be gone.
    }
    expired()
  }, [expired])

  const { refetch } = me
  const value = useMemo(() => {
    const current = me.data
    return {
      me: current,
      signedIn,
      signOut,
      expired,
      can: (role: Role) => (current ? includes(current.role, role) : false),
      unavailable: me.isError,
      retry: () => void refetch(),
    }
  }, [me.data, me.isError, refetch, signedIn, signOut, expired])

  return <AuthContext value={value}>{children}</AuthContext>
}
