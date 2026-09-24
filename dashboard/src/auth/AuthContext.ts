import { createContext } from 'react'

export interface Auth {
  token: string | null
  signIn: (token: string) => void
  signOut: () => void
}

export const AuthContext = createContext<Auth | null>(null)
