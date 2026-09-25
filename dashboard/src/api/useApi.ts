import { useCallback } from 'react'
import { useAuth } from '../auth/useAuth'
import { ApiError, apiRequest, type RequestOptions } from './client'

/** Request function for signed-in pages; a 401 means the session ended, so sign out. */
export function useApi() {
  const { expired } = useAuth()
  return useCallback(
    async <T>(path: string, options?: RequestOptions): Promise<T> => {
      try {
        return await apiRequest<T>(path, options)
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) expired()
        throw error
      }
    },
    [expired],
  )
}
