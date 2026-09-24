import { useState, type FormEvent } from 'react'
import { ApiError } from '../../api/client'
import {
  useAlertChannels,
  useCreateAlertChannel,
  useDeleteAlertChannel,
  useTestAlertChannel,
} from '../../api/queries'
import type { AlertChannel, ChannelType, CreatedAlertChannel } from '../../api/types'
import { formatDateUTC } from '../../lib/format'

export function ChannelsSection() {
  const channels = useAlertChannels()
  const [adding, setAdding] = useState(false)
  const [created, setCreated] = useState<CreatedAlertChannel | null>(null)

  return (
    <section className="card" aria-labelledby="channels-title">
      <div className="card-header">
        <div>
          <h2 id="channels-title">Alert channels</h2>
          <p className="muted section-hint">
            Slack incoming webhooks or any HTTPS endpoint. URLs are stored encrypted.
          </p>
        </div>
        {!adding && (
          <button
            type="button"
            className="button"
            onClick={() => {
              setCreated(null)
              setAdding(true)
            }}
          >
            Add channel
          </button>
        )}
      </div>
      <div className="card-body">
        {created?.signing_secret && (
          <div className="new-key" role="status">
            <p>
              <strong>Webhook added.</strong> Save its signing secret now: it won't be shown again.
            </p>
            <div className="new-key-value">
              <code aria-label="Signing secret">{created.signing_secret}</code>
            </div>
            <p className="secondary">
              Verify <code>X-Tollbooth-Signature</code> as HMAC-SHA256 of{' '}
              <code>{'{X-Tollbooth-Timestamp}.{body}'}</code>.
            </p>
            <button type="button" className="button button-ghost" onClick={() => setCreated(null)}>
              Done
            </button>
          </div>
        )}
        {adding && (
          <ChannelForm
            onCancel={() => setAdding(false)}
            onCreated={(channel) => {
              setAdding(false)
              setCreated(channel)
            }}
          />
        )}
        {channels.data?.length === 0 && !adding && (
          <p className="secondary">No channels yet. Budgets can still block without them.</p>
        )}
        {channels.data && channels.data.length > 0 && (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">Name</th>
                  <th scope="col">Type</th>
                  <th scope="col">Host</th>
                  <th scope="col">Added</th>
                  <th scope="col">
                    <span className="visually-hidden">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {channels.data.map((c) => (
                  <ChannelRow key={c.id} channel={c} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </section>
  )
}

function ChannelRow({ channel }: { channel: AlertChannel }) {
  const test = useTestAlertChannel()
  const remove = useDeleteAlertChannel()
  const [confirming, setConfirming] = useState(false)
  const result = test.data

  return (
    <tr>
      <th scope="row">{channel.name}</th>
      <td>{channel.type === 'slack' ? 'Slack' : 'Webhook'}</td>
      <td>
        <code>{channel.url_hint}</code>
      </td>
      <td className="secondary">{formatDateUTC(channel.created_at)}</td>
      <td className="actions-cell">
        <span className="confirm">
          {result && (
            <span className={result.ok ? 'secondary' : 'error-text'} role="status">
              {result.ok ? 'Test sent' : `Test failed: ${result.error}`}
            </span>
          )}
          {confirming ? (
            <>
              <button type="button" className="button" onClick={() => setConfirming(false)}>
                Cancel
              </button>
              <button
                type="button"
                className="button button-danger"
                disabled={remove.isPending}
                onClick={() => remove.mutate(channel.id)}
              >
                Delete channel
              </button>
            </>
          ) : (
            <>
              <button
                type="button"
                className="button"
                disabled={test.isPending}
                onClick={() => test.mutate(channel.id)}
                aria-label={`Send test to ${channel.name}`}
              >
                {test.isPending ? 'Sending…' : 'Send test'}
              </button>
              <button
                type="button"
                className="button button-ghost button-danger"
                onClick={() => setConfirming(true)}
                aria-label={`Delete ${channel.name}`}
              >
                Delete
              </button>
            </>
          )}
        </span>
      </td>
    </tr>
  )
}

interface FormProps {
  onCancel: () => void
  onCreated: (channel: CreatedAlertChannel) => void
}

function ChannelForm({ onCancel, onCreated }: FormProps) {
  const create = useCreateAlertChannel()
  const [name, setName] = useState('')
  const [type, setType] = useState<ChannelType>('slack')
  const [url, setUrl] = useState('')

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    onCreated(await create.mutateAsync({ name: name.trim(), type, url: url.trim() }))
  }

  const error =
    create.error instanceof ApiError && create.error.status === 409
      ? 'A channel with that name already exists.'
      : create.error?.message

  return (
    <form className="inline-form" onSubmit={(e) => void submit(e).catch(() => {})}>
      <label className="field">
        <span className="field-label">Name</span>
        <input
          className="input"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="#llm-costs"
          autoFocus
        />
      </label>
      <label className="field">
        <span className="field-label">Type</span>
        <select
          className="select"
          value={type}
          onChange={(e) => setType(e.target.value as ChannelType)}
        >
          <option value="slack">Slack incoming webhook</option>
          <option value="webhook">Webhook (signed JSON)</option>
        </select>
      </label>
      <label className="field field-wide">
        <span className="field-label">URL</span>
        <input
          className="input"
          type="url"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://hooks.slack.com/services/…"
          autoComplete="off"
        />
      </label>
      <div className="form-actions">
        <button type="button" className="button" onClick={onCancel}>
          Cancel
        </button>
        <button
          type="submit"
          className="button button-primary"
          disabled={create.isPending || !name.trim() || !url.trim()}
        >
          {create.isPending ? 'Adding…' : 'Add channel'}
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
