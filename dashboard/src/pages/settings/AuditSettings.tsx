import { useState } from 'react'
import { useAuditLog } from '../../api/queries'
import { summarize } from '../../lib/audit'
import { formatDateTimeUTC } from '../../lib/format'

const ACTIONS = [
  'auth.login',
  'auth.login_failed',
  'auth.login_throttled',
  'key.created',
  'key.revoked',
  'credential.created',
  'budget.created',
  'budget.updated',
  'budget.deleted',
  'channel.created',
  'channel.deleted',
  'user.created',
  'user.updated',
  'user.password_reset',
  'api_token.created',
  'api_token.deleted',
]

export function AuditSettings() {
  const [action, setAction] = useState('')
  const log = useAuditLog(action)
  const events = log.data?.pages.flat() ?? []

  return (
    <section className="card" aria-labelledby="audit-title">
      <div className="card-header">
        <div>
          <h2 id="audit-title">Audit log</h2>
          <p className="muted section-hint">
            Sign-ins and every change to keys, credentials, budgets, channels, users, and tokens.
            Secrets are never recorded.
          </p>
        </div>
        <label className="visually-hidden" htmlFor="audit-action">
          Action
        </label>
        <select
          id="audit-action"
          className="select"
          value={action}
          onChange={(e) => setAction(e.target.value)}
        >
          <option value="">All actions</option>
          {ACTIONS.map((a) => (
            <option key={a} value={a}>
              {a}
            </option>
          ))}
        </select>
      </div>
      <div className="card-body">
        {log.error && (
          <p className="error-text" role="alert">
            Could not load the audit log: {log.error.message}
          </p>
        )}
        {log.data && events.length === 0 && <p className="secondary">Nothing recorded yet.</p>}
        {events.length > 0 && (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">Time (UTC)</th>
                  <th scope="col">Who</th>
                  <th scope="col">Action</th>
                  <th scope="col">Details</th>
                </tr>
              </thead>
              <tbody>
                {events.map((e) => (
                  <tr key={e.id}>
                    <td className="secondary">
                      {formatDateTimeUTC(e.created_at).replace(' UTC', '')}
                    </td>
                    <td>{e.actor_label}</td>
                    <td>
                      <code>{e.action}</code>
                    </td>
                    <td className="audit-details">{summarize(e)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {log.hasNextPage && (
          <button
            type="button"
            className="button load-more"
            disabled={log.isFetchingNextPage}
            onClick={() => void log.fetchNextPage()}
          >
            Load more
          </button>
        )}
      </div>
    </section>
  )
}
