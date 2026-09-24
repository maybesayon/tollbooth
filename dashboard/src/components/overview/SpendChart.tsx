import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  type TooltipContentProps,
} from 'recharts'
import type { Interval } from '../../api/types'
import { bucketLabel, bucketTitle } from '../../lib/dates'
import { formatUSD, formatUSDTick } from '../../lib/format'
import type { Series, StackRow } from '../../lib/series'

interface Props {
  rows: StackRow[]
  series: Series[]
  interval: Interval
}

export function SpendChart({ rows, series, interval }: Props) {
  const showLegend = series.length > 1

  return (
    <div className="spend-chart">
      {showLegend && <Legend series={series} />}
      <div className="chart-frame">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart
            data={rows}
            margin={{ top: 8, right: 4, bottom: 0, left: 4 }}
            barCategoryGap="20%"
          >
            <CartesianGrid vertical={false} stroke="var(--gridline)" strokeWidth={1} />
            <XAxis
              dataKey="bucket"
              tickFormatter={(b: string) => bucketLabel(b, interval)}
              tick={{ fill: 'var(--text-muted)', fontSize: 12 }}
              tickLine={false}
              axisLine={{ stroke: 'var(--baseline)' }}
              minTickGap={24}
            />
            <YAxis
              tickFormatter={(v: number) => formatUSDTick(v)}
              tick={{ fill: 'var(--text-muted)', fontSize: 12 }}
              tickLine={false}
              axisLine={false}
              width={72}
            />
            <Tooltip
              cursor={{ fill: 'var(--hover)' }}
              content={(props) => <ChartTooltip {...props} series={series} interval={interval} />}
              isAnimationActive={false}
            />
            {series.map((s, i) => (
              <Bar
                key={s.key}
                dataKey={s.key}
                name={s.key}
                stackId="spend"
                fill={s.color}
                stroke="var(--surface)"
                strokeWidth={2}
                maxBarSize={24}
                radius={i === series.length - 1 ? [4, 4, 0, 0] : 0}
                isAnimationActive={false}
              />
            ))}
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}

function Legend({ series }: { series: Series[] }) {
  return (
    <ul className="legend" aria-label="Legend">
      {series.map((s) => (
        <li key={s.key}>
          <span className="legend-swatch" style={{ background: s.color }} aria-hidden="true" />
          {s.key}
        </li>
      ))}
    </ul>
  )
}

type TooltipProps = TooltipContentProps & { series: Series[]; interval: Interval }

function ChartTooltip({ active, payload, label, series, interval }: TooltipProps) {
  if (!active || !payload?.length) return null
  const byKey = new Map(payload.map((p) => [String(p.dataKey), Number(p.value ?? 0)]))
  const total = [...byKey.values()].reduce((sum, v) => sum + v, 0)
  const rows = series.filter((s) => (byKey.get(s.key) ?? 0) > 0).reverse()
  return (
    <div className="chart-tooltip">
      <div className="chart-tooltip-title">{bucketTitle(String(label), interval)}</div>
      <div className="chart-tooltip-total">
        <strong>{formatUSD(total)}</strong>
        {series.length > 1 && <span className="muted"> total</span>}
      </div>
      {series.length > 1 &&
        rows.map((s) => (
          <div key={s.key} className="chart-tooltip-row">
            <span className="line-key" style={{ background: s.color }} aria-hidden="true" />
            <strong>{formatUSD(byKey.get(s.key) ?? 0)}</strong>
            <span className="secondary">{s.key}</span>
          </div>
        ))}
    </div>
  )
}
