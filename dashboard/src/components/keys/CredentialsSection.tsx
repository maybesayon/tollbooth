import { useState, type FormEvent } from 'react'
import { ApiError } from '../../api/client'
import { useCreateCredential, useCredentials } from '../../api/queries'
import type { Provider } from '../../api/types'
import { formatDateTimeUTC, formatDateUTC } from '../../lib/format'
import { ProviderName } from '../ProviderName'

export function CredentialsSection() {
  const credentials = useCredentials()
  const [adding, setAdding] = useState(false)

  return (
    <section className="card" aria-labelledby="credentials-title">
      <div className="card-header">
        <div>
          <h2 id="credentials-title">Provider credentials</h2>
          <p className="muted section-hint">
            Real provider API keys, stored encrypted. They are never shown again after saving.
          </p>
        </div>
        {!adding && (
          <button type="button" className="button" onClick={() => setAdding(true)}>
            Add credential
          </button>
        )}
      </div>
      <div className="card-body">
        {adding && <CredentialForm onDone={() => setAdding(false)} />}
        {credentials.error && (
          <p className="error-text" role="alert">
            Could not load credentials: {credentials.error.message}
          </p>
        )}
        {credentials.data?.length === 0 && !adding && (
          <p className="secondary">
            No credentials yet. Add a provider key before creating virtual keys.
          </p>
        )}
        {credentials.data && credentials.data.length > 0 && (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">Name</th>
                  <th scope="col">Provider</th>
                  <th scope="col">Added</th>
                </tr>
              </thead>
              <tbody>
                {credentials.data.map((c) => (
                  <tr key={c.id}>
                    <th scope="row">{c.name}</th>
                    <td>
                      <ProviderName provider={c.provider} />
                    </td>
                    <td className="secondary" title={formatDateTimeUTC(c.created_at)}>
                      {formatDateUTC(c.created_at)}
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

function CredentialForm({ onDone }: { onDone: () => void }) {
  const create = useCreateCredential()
  const [name, setName] = useState('')
  const [provider, setProvider] = useState<Provider>('openai')
  const [apiKey, setApiKey] = useState('')

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    await create.mutateAsync({ name: name.trim(), provider, api_key: apiKey.trim() })
    onDone()
  }

  const error =
    create.error instanceof ApiError && create.error.status === 409
      ? 'A credential with that name already exists.'
      : create.error?.message

  return (
    <form className="inline-form" onSubmit={(e) => void submit(e).catch(() => {})}>
      <label className="field">
        <span className="field-label">Name</span>
        <input
          className="input"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="openai-prod"
          required
          autoFocus
        />
      </label>
      <label className="field">
        <span className="field-label">Provider</span>
        <select
          className="select"
          value={provider}
          onChange={(e) => setProvider(e.target.value as Provider)}
        >
          <option value="openai">OpenAI</option>
          <option value="anthropic">Anthropic</option>
        </select>
      </label>
      <label className="field field-wide">
        <span className="field-label">API key</span>
        <input
          className="input"
          type="password"
          autoComplete="off"
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          required
        />
      </label>
      <div className="form-actions">
        <button type="button" className="button" onClick={onDone}>
          Cancel
        </button>
        <button
          type="submit"
          className="button button-primary"
          disabled={create.isPending || !name.trim() || !apiKey.trim()}
        >
          {create.isPending ? 'Saving…' : 'Save credential'}
        </button>
      </div>
      {error && (
        <p className="error-text form-error" role="alert">
          {error}
        </p>
      )}
    </form>
  )
}
