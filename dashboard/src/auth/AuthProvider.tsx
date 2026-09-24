import { useCallback, useMemo, useState, type ReactNode } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { AuthContext } from './AuthContext'
import { readToken, writeToken } from './tokenStore'

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(readToken)
  const queryClient = useQueryClient()

  const signIn = useCallback((next: string) => {
    writeToken(next)
    setToken(next)
  }, [])

  const signOut = useCallback(() => {
    writeToken(null)
    setToken(null)
    queryClient.clear()
  }, [queryClient])

  const value = useMemo(() => ({ token, signIn, signOut }), [token, signIn, signOut])
  return <AuthContext value={value}>{children}</AuthContext>
}
