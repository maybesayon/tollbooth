import { createContext } from 'react'
import type { Me, Role } from '../api/types'

export interface Auth {
  /** undefined while the session is being checked, null when signed out. */
  me: Me | null | undefined
  signedIn: (me: Me) => void
  signOut: () => Promise<void>
  /** The server rejected our session (expired, revoked, user disabled). */
  expired: () => void
  can: (role: Role) => boolean
  /** Checking the session failed for a reason other than being signed out. */
  unavailable: boolean
  retry: () => void
}

export const AuthContext = createContext<Auth | null>(null)
