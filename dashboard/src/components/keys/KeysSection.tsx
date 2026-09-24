import { useMemo, useState, type FormEvent } from 'react'
import { useCreateKey, useCredentials, useKeys, useRevokeKey } from '../../api/queries'
import type { CreatedKey, VirtualKey } from '../../api/types'
import { formatDateTimeUTC, formatDateUTC } from '../../lib/format'
import { Badge } from '../Badge'
import { PROVIDER_NAMES } from '../../lib/labels'
import { ProviderName } from '../ProviderName'

export function KeysSection() {
  const [showRevoked, setShowRevoked] = useState(false)
  const [creating, setCreating] = useState(false)
  const [created, setCreated] = useState<CreatedKey | null>(null)
  const keys = useKeys(true)
  const credentials = useCredentials()

  const visible = useMemo(
    () => (keys.data ?? []).filter((k) => showRevoked || k.revoked_at === null).reverse(),
    [keys.data, showRevoked],
  )
  const teams = useMemo(
    () => [...new Set((keys.data ?? []).map((k) => k.team))].sort(),
    [keys.data],
  )
  const revokedCount = (keys.data ?? []).filter((k) => k.revoked_at !== null).length
  const hasCredentials = (credentials.data?.length ?? 0) > 0

  return (
    <section className="card" aria-labelledby="keys-title">
      <div className="card-header">
        <div>
          <h2 id="keys-title">Virtual keys</h2>
          <p className="muted section-hint">
            Give one to each app or team. Requests made with it are attributed to its team.
          </p>
        </div>
        {!creating && (
          <button
            type="button"
            className="button button-primary"
            onClick={() => {
              setCreated(null)
              setCreating(true)
            }}
            disabled={!hasCredentials}
            title={hasCredentials ? undefined : 'Add a provider credential first'}
          >
            Create key
          </button>
        )}
      </div>
      <div className="card-body">
        {created && <NewKey created={created} onDismiss={() => setCreated(null)} />}
        {creating && (
          <KeyForm
            teams={teams}
            onCancel={() => setCreating(false)}
            onCreated={(key) => {
              setCreating(false)
              setCreated(key)
            }}
          />
        )}
        {keys.error && (
          <p className="error-text" role="alert">
            Could not load keys: {keys.error.message}
          </p>
        )}
        {keys.data?.length === 0 && !creating && <p className="secondary">No virtual keys yet.</p>}
        {visible.length > 0 && (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">Name</th>
                  <th scope="col">Team</th>
                  <th scope="col">Provider</th>
                  <th scope="col">Key</th>
                  <th scope="col">Created</th>
                  <th scope="col">Status</th>
                  <th scope="col">
                    <span className="visually-hidden">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {visible.map((key) => (
                  <KeyRow key={key.id} vkey={key} />
                ))}
              </tbody>
            </table>
          </div>
        )}
        {revokedCount > 0 && (
          <label className="checkbox">
            <input
              type="checkbox"
              checked={showRevoked}
              onChange={(e) => setShowRevoked(e.target.checked)}
            />
            Show {revokedCount} revoked {revokedCount === 1 ? 'key' : 'keys'}
          </label>
        )}
      </div>
    </section>
  )
}

function KeyRow({ vkey }: { vkey: VirtualKey }) {
  const revoke = useRevokeKey()
  const [confirming, setConfirming] = useState(false)
  const revoked = vkey.revoked_at !== null

  return (
    <tr className={revoked ? 'row-revoked' : undefined}>
      <th scope="row">{vkey.name}</th>
      <td>{vkey.team}</td>
      <td>
        <ProviderName provider={vkey.provider} />
      </td>
      <td>
        <code>{vkey.key_prefix}…</code>
      </td>
      <td className="secondary" title={formatDateTimeUTC(vkey.created_at)}>
        {formatDateUTC(vkey.created_at)}
      </td>
      <td>{revoked ? <Badge tone="neutral">Revoked</Badge> : <Badge tone="good">Active</Badge>}</td>
      <td className="actions-cell">
        {!revoked && !confirming && (
          <button
            type="button"
            className="button button-ghost button-danger"
            onClick={() => setConfirming(true)}
            aria-label={`Revoke ${vkey.name}`}
          >
            Revoke
          </button>
        )}
        {!revoked && confirming && (
          <span className="confirm">
            <span className="secondary">Revoke now?</span>
            <button type="button" className="button" onClick={() => setConfirming(false)}>
              Cancel
            </button>
            <button
              type="button"
              className="button button-danger"
              disabled={revoke.isPending}
              onClick={() => revoke.mutate(vkey.id, { onSettled: () => setConfirming(false) })}
            >
              Revoke key
            </button>
          </span>
        )}
      </td>
    </tr>
  )
}

interface KeyFormProps {
  teams: string[]
  onCancel: () => void
  onCreated: (key: CreatedKey) => void
}

function KeyForm({ teams, onCancel, onCreated }: KeyFormProps) {
  const credentials = useCredentials()
  const create = useCreateKey()
  const [name, setName] = useState('')
  const [team, setTeam] = useState('')
  const [credentialId, setCredentialId] = useState(credentials.data?.[0]?.id ?? '')

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    onCreated(
      await create.mutateAsync({
        name: name.trim(),
        team: team.trim(),
        credential_id: credentialId,
      }),
    )
  }

  return (
    <form className="inline-form" onSubmit={(e) => void submit(e).catch(() => {})}>
      <label className="field">
        <span className="field-label">Name</span>
        <input
          className="input"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="search-api"
          required
          autoFocus
        />
      </label>
      <label className="field">
        <span className="field-label">Team</span>
        <input
          className="input"
          value={team}
          onChange={(e) => setTeam(e.target.value)}
          list="team-options"
          placeholder="search"
          required
        />
        <datalist id="team-options">
          {teams.map((t) => (
            <option key={t} value={t} />
          ))}
        </datalist>
      </label>
      <label className="field field-wide">
        <span className="field-label">Provider credential</span>
        <select
          className="select"
          value={credentialId}
          onChange={(e) => setCredentialId(e.target.value)}
          required
        >
          {credentials.data?.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name} ({PROVIDER_NAMES[c.provider]})
            </option>
          ))}
        </select>
      </label>
      <div className="form-actions">
        <button type="button" className="button" onClick={onCancel}>
          Cancel
        </button>
        <button
          type="submit"
          className="button button-primary"
          disabled={create.isPending || !name.trim() || !team.trim() || !credentialId}
        >
          {create.isPending ? 'Creating…' : 'Create key'}
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

function NewKey({ created, onDismiss }: { created: CreatedKey; onDismiss: () => void }) {
  const [copied, setCopied] = useState(false)

  async function copy() {
    try {
      await navigator.clipboard.writeText(created.key)
      setCopied(true)
    } catch {
      setCopied(false)
    }
  }

  const baseUrl =
    created.provider === 'openai' ? `${window.location.origin}/v1` : window.location.origin

  return (
    <div className="new-key" role="status">
      <p>
        <strong>Key created for {created.team}.</strong> Copy it now: it won't be shown again.
      </p>
      <div className="new-key-value">
        <code aria-label="New virtual key">{created.key}</code>
        <button type="button" className="button" onClick={() => void copy()}>
          {copied ? 'Copied' : 'Copy'}
        </button>
      </div>
      <p className="secondary">
        Use it as the API key with base URL <code>{baseUrl}</code> in the{' '}
        <ProviderName provider={created.provider} /> SDK.
      </p>
      <button type="button" className="button button-ghost" onClick={onDismiss}>
        Done
      </button>
    </div>
  )
}
