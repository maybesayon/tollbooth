import type { GroupBy, SpendReport } from '../../api/types'
import { formatInt, formatPercent, formatUSD, formatUSDExact } from '../../lib/format'

const HEADINGS: Record<GroupBy, string> = {
  team: 'Team',
  model: 'Model',
  provider: 'Provider',
  key: 'Key',
}

interface Props {
  report: SpendReport
  /** The chart's color for each group, when the chart is split the same way. */
  colorOf: ((group: string) => string | undefined) | null
}

export function BreakdownTable({ report, colorOf }: Props) {
  const totalCost = Number(report.total.cost_usd)
  return (
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr>
            <th scope="col">{HEADINGS[report.group_by]}</th>
            <th scope="col" className="num">
              Requests
            </th>
            <th scope="col" className="num">
              Errors
            </th>
            <th scope="col" className="num">
              Input tokens
            </th>
            <th scope="col" className="num">
              Output tokens
            </th>
            <th scope="col" className="num">
              Spend
            </th>
            <th scope="col" className="num">
              Share
            </th>
          </tr>
        </thead>
        <tbody>
          {report.groups.map((g) => (
            <tr key={g.group}>
              <th scope="row">
                <span className="group-cell">
                  {colorOf && (
                    <span
                      className="legend-swatch"
                      style={{ background: colorOf(g.group) }}
                      aria-hidden="true"
                    />
                  )}
                  {g.group}
                </span>
              </th>
              <td className="num">{formatInt(g.requests)}</td>
              <td className="num">{formatInt(g.error_requests)}</td>
              <td className="num">
                {formatInt(g.input_tokens + g.cache_read_tokens + g.cache_write_tokens)}
              </td>
              <td className="num">{formatInt(g.output_tokens)}</td>
              <td className="num" title={formatUSDExact(g.cost_usd)}>
                {formatUSD(g.cost_usd)}
                {g.unpriced_requests > 0 && (
                  <span className="muted" title={`${g.unpriced_requests} unpriced`}>
                    {' '}
                    *
                  </span>
                )}
              </td>
              <td className="num">{formatPercent(Number(g.cost_usd), totalCost)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
