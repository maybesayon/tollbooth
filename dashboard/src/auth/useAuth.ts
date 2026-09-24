import { useContext } from 'react'
import { AuthContext, type Auth } from './AuthContext'

export function useAuth(): Auth {
  const auth = useContext(AuthContext)
  if (auth === null) throw new Error('useAuth must be used inside <AuthProvider>')
  return auth
}
