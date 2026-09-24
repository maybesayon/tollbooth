const KEY = 'tollbooth.adminToken'

export function readToken(): string | null {
  try {
    return sessionStorage.getItem(KEY)
  } catch {
    return null
  }
}

export function writeToken(token: string | null): void {
  try {
    if (token === null) sessionStorage.removeItem(KEY)
    else sessionStorage.setItem(KEY, token)
  } catch {
    // Storage unavailable (private mode, blocked); the session simply won't survive a reload.
  }
}
