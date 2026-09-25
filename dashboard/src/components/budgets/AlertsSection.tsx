import { useAlerts } from '../../api/queries'
import type { AlertDelivery } from '../../api/types'
import { formatDateTimeUTC, formatUSD } from '../../lib/format'
import { Badge } from '../Badge'

export function AlertsSection() {
  const alerts = useAlerts()
  return (
    <section className="card" aria-labelledby="alerts-title">
      <div className="card-header">
        <h2 id="alerts-title">Recent alerts</h2>
      </div>
      <div className="card-body">
        {alerts.error && (
          <p className="error-text" role="alert">
            Could not load alerts: {alerts.error.message}
          </p>
        )}
        {alerts.data?.length === 0 && (
          <p className="secondary">
            No alerts yet. Each budget alerts once per period for every threshold it crosses.
          </p>
        )}
        {alerts.data && alerts.data.length > 0 && (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">Time (UTC)</th>
                  <th scope="col">Budget</th>
                  <th scope="col" className="num">
                    Threshold
                  </th>
                  <th scope="col" className="num">
                    Spend
                  </th>
                  <th scope="col">Delivery</th>
                </tr>
              </thead>
              <tbody>
                {alerts.data.map((alert) => (
                  <tr key={alert.id}>
                    <td className="secondary">
                      {formatDateTimeUTC(alert.created_at).replace(' UTC', '')}
                    </td>
                    <th scope="row">{alert.budget_name}</th>
                    <td className="num">{alert.threshold_percent}%</td>
                    <td className="num">
                      {formatUSD(alert.spend_usd)}
                      <span className="muted"> / {formatUSD(alert.limit_usd)}</span>
                    </td>
                    <td>
                      <span className="deliveries">
                        {alert.deliveries.length === 0 && (
                          <span className="muted">No channels</span>
                        )}
                        {alert.deliveries.map((d) => (
                          <DeliveryBadge key={d.channel_id} delivery={d} />
                        ))}
                      </span>
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

function DeliveryBadge({ delivery }: { delivery: AlertDelivery }) {
  const { status, attempts, last_error, channel_name } = delivery
  const title =
    status === 'failed'
      ? `Failed after ${attempts} attempts: ${last_error ?? 'unknown error'}`
      : status === 'skipped'
        ? `Not sent: ${last_error ?? 'skipped'}`
        : `${attempts} attempt${attempts === 1 ? '' : 's'}`
  const tone = status === 'delivered' ? 'good' : status === 'failed' ? 'critical' : 'neutral'
  const suffix = status === 'pending' ? ' (sending)' : status === 'skipped' ? ' (skipped)' : ''
  return (
    <span title={title}>
      <Badge tone={tone}>{`${channel_name}${suffix}`}</Badge>
    </span>
  )
}
