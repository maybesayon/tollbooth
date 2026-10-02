import { useState, type FormEvent } from 'react'
import { useCreateUser, useResetPassword, useUpdateUser, useUsers } from '../../api/queries'
import type { Role, User } from '../../api/types'
import { ROLE_LABELS } from '../../auth/roles'
import { useAuth } from '../../auth/useAuth'
import { Badge } from '../../components/Badge'
import { formatDateTimeUTC } from '../../lib/format'

interface Secret {
  email: string
  password: string
}

export function UsersSettings() {
  const users = useUsers()
  const [adding, setAdding] = useState(false)
  const [secret, setSecret] = useState<Secret | null>(null)

  return (
    <section className="card" aria-labelledby="users-title">
      <div className="card-header">
        <div>
          <h2 id="users-title">Users</h2>
          <p className="muted section-hint">
            Viewers see everything; editors also manage keys, budgets, and channels; admins also
            manage credentials and users.
          </p>
        </div>
        {!adding && (
          <button type="button" className="button button-primary" onClick={() => setAdding(true)}>
            Add user
          </button>
        )}
      </div>
      <div className="card-body">
        {secret && (
          <div className="new-key" role="status">
            <p>
              <strong>Temporary password for {secret.email}.</strong> Share it securely; it won't be
              shown again. They can change it under Settings.
            </p>
            <div className="new-key-value">
              <code aria-label="Temporary password">{secret.password}</code>
            </div>
            <button type="button" className="button button-ghost" onClick={() => setSecret(null)}>
              Done
            </button>
          </div>
        )}
        {adding && (
          <UserForm
            onCancel={() => setAdding(false)}
            onCreated={(created) => {
              setAdding(false)
              setSecret(created)
            }}
          />
        )}
        {users.error && (
          <p className="error-text" role="alert">
            Could not load users: {users.error.message}
          </p>
        )}
        {users.data && (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">Name</th>
                  <th scope="col">Email</th>
                  <th scope="col">Role</th>
                  <th scope="col">Status</th>
                  <th scope="col">Last sign-in</th>
                  <th scope="col">
                    <span className="visually-hidden">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {users.data.map((u) => (
                  <UserRow key={u.id} user={u} onReset={setSecret} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </section>
  )
}

function UserRow({ user, onReset }: { user: User; onReset: (secret: Secret) => void }) {
  const { me } = useAuth()
  const update = useUpdateUser()
  const reset = useResetPassword()
  const isSelf = me?.user?.id === user.id

  return (
    <tr className={user.active ? undefined : 'row-revoked'}>
      <th scope="row">
        {user.name}
        {isSelf && <span className="muted"> (you)</span>}
      </th>
      <td>{user.email}</td>
      <td>
        <label className="visually-hidden" htmlFor={`role-${user.id}`}>
          Role for {user.email}
        </label>
        <select
          id={`role-${user.id}`}
          className="select"
          value={user.role}
          disabled={isSelf || update.isPending}
          onChange={(e) => update.mutate({ id: user.id, role: e.target.value as Role })}
        >
          {(['viewer', 'editor', 'admin'] as const).map((r) => (
            <option key={r} value={r}>
              {ROLE_LABELS[r]}
            </option>
          ))}
        </select>
      </td>
      <td>
        {user.active ? <Badge tone="good">Active</Badge> : <Badge tone="neutral">Disabled</Badge>}
      </td>
      <td className="secondary">
        {user.last_login_at ? formatDateTimeUTC(user.last_login_at) : 'Never'}
      </td>
      <td className="actions-cell">
        <span className="confirm">
          {update.error && (
            <span className="error-text" role="alert">
              {update.error.message}
            </span>
          )}
          <button
            type="button"
            className="button"
            disabled={reset.isPending}
            onClick={() =>
              reset.mutate(user.id, {
                onSuccess: (r) => onReset({ email: user.email, password: r.temporary_password }),
              })
            }
            aria-label={`Reset password for ${user.email}`}
          >
            Reset password
          </button>
          {!isSelf && (
            <button
              type="button"
              className={user.active ? 'button button-ghost button-danger' : 'button button-ghost'}
              disabled={update.isPending}
              onClick={() => update.mutate({ id: user.id, disabled: user.active })}
              aria-label={`${user.active ? 'Disable' : 'Enable'} ${user.email}`}
            >
              {user.active ? 'Disable' : 'Enable'}
            </button>
          )}
        </span>
      </td>
    </tr>
  )
}

interface FormProps {
  onCancel: () => void
  onCreated: (secret: Secret) => void
}

function UserForm({ onCancel, onCreated }: FormProps) {
  const create = useCreateUser()
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [role, setRole] = useState<Role>('viewer')

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const user = await create.mutateAsync({ name: name.trim(), email: email.trim(), role })
    onCreated({ email: user.email, password: user.temporary_password ?? '' })
  }

  return (
    <form
      className="inline-form"
      onSubmit={(e) => void submit(e).catch(() => {})}
      aria-label="New user"
    >
      <label className="field">
        <span className="field-label">Name</span>
        <input className="input" value={name} onChange={(e) => setName(e.target.value)} autoFocus />
      </label>
      <label className="field">
        <span className="field-label">Email</span>
        <input
          className="input"
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
      </label>
      <label className="field">
        <span className="field-label">Role</span>
        <select className="select" value={role} onChange={(e) => setRole(e.target.value as Role)}>
          <option value="viewer">Viewer</option>
          <option value="editor">Editor</option>
          <option value="admin">Admin</option>
        </select>
      </label>
      <div className="form-actions">
        <button type="button" className="button" onClick={onCancel}>
          Cancel
        </button>
        <button
          type="submit"
          className="button button-primary"
          disabled={create.isPending || !name.trim() || !email.trim()}
        >
          Add user
        </button>
      </div>
      {create.error && (
        <p className="error-text form-error" role="alert">
          {create.error.message}
        </p>
      )}
    </form>
  )
}
