import { useQuery } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { ApiError, apiRequest } from '../api/client'
import type { Me, SetupStatus } from '../api/types'
import { useAuth } from '../auth/useAuth'
import './LoginPage.css'

export function LoginPage() {
  const setup = useQuery({
    queryKey: ['setup'],
    queryFn: () => apiRequest<SetupStatus>('/auth/setup'),
    retry: false,
  })

  return (
    <main className="login">
      <div className="card login-card">
        <div className="login-brand">
          <img src={`${import.meta.env.BASE_URL}favicon.svg`} alt="" width={28} height={28} />
          <h1>Tollbooth</h1>
        </div>
        {setup.data?.needs_setup ? (
          setup.data.setup_with_admin_token ? (
            <SetupForm />
          ) : (
            <p className="secondary">
              No accounts exist yet. Create the first admin on the server with{' '}
              <code>tollbooth create-user --email you@example.com --name You</code>, then reload.
            </p>
          )
        ) : (
          <SignInForm />
        )}
      </div>
    </main>
  )
}

function SignInForm() {
  const { signedIn } = useAuth()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState(false)

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setPending(true)
    setError(null)
    try {
      signedIn(await apiRequest<Me>('/auth/login', { method: 'POST', body: { email, password } }))
    } catch (e) {
      setError(describe(e))
    } finally {
      setPending(false)
    }
  }

  return (
    <form className="login-form" onSubmit={(e) => void submit(e)} aria-label="Sign in">
      <label className="field">
        <span className="field-label">Email</span>
        <input
          className="input"
          type="email"
          autoComplete="username"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          autoFocus
        />
      </label>
      <label className="field">
        <span className="field-label">Password</span>
        <input
          className="input"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
      </label>
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
      <button
        className="button button-primary"
        type="submit"
        disabled={pending || !email.trim() || !password}
      >
        {pending ? 'Signing in…' : 'Sign in'}
      </button>
    </form>
  )
}

function SetupForm() {
  const { signedIn } = useAuth()
  const [adminToken, setAdminToken] = useState('')
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState(false)

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setPending(true)
    setError(null)
    try {
      signedIn(
        await apiRequest<Me>('/auth/setup', {
          method: 'POST',
          body: { admin_token: adminToken, name, email, password },
        }),
      )
    } catch (e) {
      setError(
        e instanceof ApiError && e.status === 403 ? 'That admin token was rejected.' : describe(e),
      )
    } finally {
      setPending(false)
    }
  }

  return (
    <form className="login-form" onSubmit={(e) => void submit(e)} aria-label="Create admin account">
      <p className="secondary">
        Welcome. Create the first admin account using the server's admin token (
        <code>TOLLBOOTH_ADMIN_TOKEN</code>).
      </p>
      <label className="field">
        <span className="field-label">Admin token</span>
        <input
          className="input"
          type="password"
          autoComplete="off"
          value={adminToken}
          onChange={(e) => setAdminToken(e.target.value)}
          autoFocus
        />
      </label>
      <label className="field">
        <span className="field-label">Your name</span>
        <input className="input" value={name} onChange={(e) => setName(e.target.value)} />
      </label>
      <label className="field">
        <span className="field-label">Email</span>
        <input
          className="input"
          type="email"
          autoComplete="username"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
      </label>
      <label className="field">
        <span className="field-label">Password (at least 12 characters)</span>
        <input
          className="input"
          type="password"
          autoComplete="new-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
      </label>
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
      <button
        className="button button-primary"
        type="submit"
        disabled={pending || !adminToken || !name.trim() || !email.trim() || password.length < 12}
      >
        {pending ? 'Creating…' : 'Create admin account'}
      </button>
    </form>
  )
}

function describe(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 401) return 'Wrong email or password.'
    if (error.status === 429) return 'Too many attempts. Wait a few minutes and try again.'
    return error.message
  }
  return 'Could not reach Tollbooth. Is the server running?'
}
