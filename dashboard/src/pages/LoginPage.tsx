import { useState, type FormEvent } from 'react'
import { ApiError, apiRequest } from '../api/client'
import { useAuth } from '../auth/useAuth'
import './LoginPage.css'

export function LoginPage() {
  const { signIn } = useAuth()
  const [token, setToken] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState(false)

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const candidate = token.trim()
    if (!candidate) return
    setPending(true)
    setError(null)
    try {
      await apiRequest(candidate, '/admin/credentials')
      signIn(candidate)
    } catch (e) {
      setError(
        e instanceof ApiError && e.status === 401
          ? 'That token was rejected.'
          : 'Could not reach Tollbooth. Is the server running?',
      )
    } finally {
      setPending(false)
    }
  }

  return (
    <main className="login">
      <form className="card login-card" onSubmit={submit}>
        <div className="login-brand">
          <img src={`${import.meta.env.BASE_URL}favicon.svg`} alt="" width={28} height={28} />
          <h1>Tollbooth</h1>
        </div>
        <p className="secondary">
          Sign in with the admin token (<code>TOLLBOOTH_ADMIN_TOKEN</code>).
        </p>
        <label className="field">
          <span className="field-label">Admin token</span>
          <input
            className="input"
            type="password"
            autoComplete="current-password"
            value={token}
            onChange={(e) => setToken(e.target.value)}
            autoFocus
          />
        </label>
        {error && (
          <p className="error-text" role="alert">
            {error}
          </p>
        )}
        <button className="button button-primary" type="submit" disabled={pending || !token.trim()}>
          {pending ? 'Checking…' : 'Sign in'}
        </button>
      </form>
    </main>
  )
}
