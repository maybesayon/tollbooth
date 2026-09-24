import { useCallback } from 'react'
import { useAuth } from '../auth/useAuth'
import { ApiError, apiRequest, type RequestOptions } from './client'

/** Authenticated request function; a 401 signs the user out. */
export function useApi() {
  const { token, signOut } = useAuth()
  return useCallback(
    async <T>(path: string, options?: RequestOptions): Promise<T> => {
      if (token === null) throw new ApiError(401, 'Not signed in')
      try {
        return await apiRequest<T>(token, path, options)
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) signOut()
        throw error
      }
    },
    [token, signOut],
  )
}
