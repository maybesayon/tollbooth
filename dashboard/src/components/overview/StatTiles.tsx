import type { Metrics } from '../../api/types'
import {
  formatCompact,
  formatInt,
  formatPercent,
  formatUSD,
  formatUSDExact,
} from '../../lib/format'

export function StatTiles({ total }: { total: Metrics }) {
  const tokens =
    total.input_tokens + total.output_tokens + total.cache_read_tokens + total.cache_write_tokens
  return (
    <section className="stats" aria-label="Summary">
      <div className="card stat stat-hero">
        <span className="stat-label">Total spend</span>
        <span className="stat-hero-value" title={formatUSDExact(total.cost_usd)}>
          {formatUSD(total.cost_usd)}
        </span>
        {total.unpriced_requests > 0 && (
          <span className="stat-note">
            <span aria-hidden="true" className="status-dot status-warning" />
            Excludes {formatInt(total.unpriced_requests)} unpriced{' '}
            {total.unpriced_requests === 1 ? 'request' : 'requests'}
          </span>
        )}
      </div>
      <div className="card stat">
        <span className="stat-label">Requests</span>
        <span className="stat-value">{formatCompact(total.requests)}</span>
        <span className="stat-note">{formatInt(total.requests)} total</span>
      </div>
      <div className="card stat">
        <span className="stat-label">Error rate</span>
        <span className="stat-value">{formatPercent(total.error_requests, total.requests)}</span>
        <span className="stat-note">
          {formatInt(total.error_requests)} of {formatInt(total.requests)} not successful
        </span>
      </div>
      <div className="card stat">
        <span className="stat-label">Tokens</span>
        <span className="stat-value">{formatCompact(tokens)}</span>
        <span className="stat-note">
          {formatCompact(total.input_tokens + total.cache_read_tokens + total.cache_write_tokens)}{' '}
          in · {formatCompact(total.output_tokens)} out
        </span>
      </div>
    </section>
  )
}
