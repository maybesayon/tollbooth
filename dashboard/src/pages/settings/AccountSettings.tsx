import { useState, type FormEvent } from 'react'
import { ApiError } from '../../api/client'
import {
  useApiTokens,
  useChangePassword,
  useCreateApiToken,
  useDeleteApiToken,
} from '../../api/queries'
import type { CreatedApiToken } from '../../api/types'
import { ROLE_LABELS } from '../../auth/roles'
import { useAuth } from '../../auth/useAuth'
import { formatDateTimeUTC, formatDateUTC } from '../../lib/format'

export function AccountSettings() {
  const { me } = useAuth()
  if (!me?.user) {
    return (
      <section className="card">
        <div className="card-body">
          <p className="secondary">
            You are using the admin token, which has no account. Sign in as a user to change a
            password or create API tokens.
          </p>
        </div>
      </section>
    )
  }
  const { user } = me
  return (
    <>
      <section className="card" aria-labelledby="profile-title">
        <div className="card-header">
          <h2 id="profile-title">Profile</h2>
        </div>
        <div className="card-body">
          <dl className="profile">
            <dt>Name</dt>
            <dd>{user.name}</dd>
            <dt>Email</dt>
            <dd>{user.email}</dd>
            <dt>Role</dt>
            <dd>{ROLE_LABELS[user.role]}</dd>
          </dl>
        </div>
      </section>
      <PasswordSection />
      <TokensSection />
    </>
  )
}

function PasswordSection() {
  const change = useChangePassword()
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [done, setDone] = useState(false)

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setDone(false)
    await change.mutateAsync({ current_password: current, new_password: next })
    setCurrent('')
    setNext('')
    setDone(true)
  }

  const error =
    change.error instanceof ApiError && change.error.status === 400
      ? 'Your current password is wrong.'
      : change.error?.message

  return (
    <section className="card" aria-labelledby="password-title">
      <div className="card-header">
        <div>
          <h2 id="password-title">Password</h2>
          <p className="muted section-hint">Changing it signs you out everywhere else.</p>
        </div>
      </div>
      <div className="card-body">
        <form className="inline-form" onSubmit={(e) => void submit(e).catch(() => {})}>
          <label className="field">
            <span className="field-label">Current password</span>
            <input
              className="input"
              type="password"
              autoComplete="current-password"
              value={current}
              onChange={(e) => setCurrent(e.target.value)}
            />
          </label>
          <label className="field">
            <span className="field-label">New password (12+ characters)</span>
            <input
              className="input"
              type="password"
              autoComplete="new-password"
              value={next}
              onChange={(e) => setNext(e.target.value)}
            />
          </label>
          <div className="form-actions">
            <button
              type="submit"
              className="button button-primary"
              disabled={change.isPending || !current || next.length < 12}
            >
              Change password
            </button>
          </div>
          {error && (
            <p className="error-text form-error" role="alert">
              {error}
            </p>
          )}
          {done && (
            <p className="secondary form-error" role="status">
              Password changed.
            </p>
          )}
        </form>
      </div>
    </section>
  )
}

function TokensSection() {
  const tokens = useApiTokens()
  const create = useCreateApiToken()
  const remove = useDeleteApiToken()
  const [name, setName] = useState('')
  const [created, setCreated] = useState<CreatedApiToken | null>(null)

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setCreated(await create.mutateAsync(name.trim()))
    setName('')
  }

  return (
    <section className="card" aria-labelledby="tokens-title">
      <div className="card-header">
        <div>
          <h2 id="tokens-title">API tokens</h2>
          <p className="muted section-hint">
            For scripts calling the admin API (<code>Authorization: Bearer …</code>). A token has
            your role.
          </p>
        </div>
      </div>
      <div className="card-body">
        {created && (
          <div className="new-key" role="status">
            <p>
              <strong>Token created.</strong> Copy it now: it won't be shown again.
            </p>
            <div className="new-key-value">
              <code aria-label="New API token">{created.token}</code>
            </div>
            <button type="button" className="button button-ghost" onClick={() => setCreated(null)}>
              Done
            </button>
          </div>
        )}
        <form className="inline-form" onSubmit={(e) => void submit(e).catch(() => {})}>
          <label className="field field-wide">
            <span className="field-label">Token name</span>
            <input
              className="input"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="nightly-report"
            />
          </label>
          <div className="form-actions">
            <button
              type="submit"
              className="button button-primary"
              disabled={create.isPending || !name.trim()}
            >
              Create token
            </button>
          </div>
        </form>
        {tokens.data && tokens.data.length > 0 && (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">Name</th>
                  <th scope="col">Token</th>
                  <th scope="col">Created</th>
                  <th scope="col">Last used</th>
                  <th scope="col">
                    <span className="visually-hidden">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {tokens.data.map((t) => (
                  <tr key={t.id}>
                    <th scope="row">{t.name}</th>
                    <td>
                      <code>{t.prefix}…</code>
                    </td>
                    <td className="secondary">{formatDateUTC(t.created_at)}</td>
                    <td className="secondary">
                      {t.last_used_at ? formatDateTimeUTC(t.last_used_at) : 'Never'}
                    </td>
                    <td className="actions-cell">
                      <button
                        type="button"
                        className="button button-ghost button-danger"
                        aria-label={`Delete token ${t.name}`}
                        disabled={remove.isPending}
                        onClick={() => remove.mutate(t.id)}
                      >
                        Delete
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </section>
  )
}
