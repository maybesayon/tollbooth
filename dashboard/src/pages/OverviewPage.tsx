import { useMemo, useState } from 'react'
import { useSearchParams } from 'react-router'
import { useSpend, useTimeseries } from '../api/queries'
import type { GroupBy, LedgerFilters, Provider } from '../api/types'
import { BreakdownTable } from '../components/overview/BreakdownTable'
import { FilterBar, type Filters } from '../components/overview/FilterBar'
import { SpendChart } from '../components/overview/SpendChart'
import { StatTiles } from '../components/overview/StatTiles'
import { resolveRange, utcDay, type RangePreset } from '../lib/dates'
import { ColorRegistry, OTHER, buildStack } from '../lib/series'
import './OverviewPage.css'

type Split = 'none' | Exclude<GroupBy, 'key'>

const SPLITS: { value: Split; label: string }[] = [
  { value: 'team', label: 'Team' },
  { value: 'model', label: 'Model' },
  { value: 'provider', label: 'Provider' },
  { value: 'none', label: 'Total' },
]

const registries = new Map<Split, ColorRegistry>()

function registryFor(split: Split): ColorRegistry {
  let registry = registries.get(split)
  if (!registry) {
    registry = new ColorRegistry()
    registries.set(split, registry)
  }
  return registry
}

function readFilters(params: URLSearchParams): Filters {
  const preset = params.get('range')
  const provider = params.get('provider')
  return {
    preset: preset === '7d' || preset === '90d' || preset === 'custom' ? preset : '30d',
    from: params.get('from') ?? '',
    to: params.get('to') ?? '',
    provider: provider === 'openai' || provider === 'anthropic' ? provider : '',
    team: params.get('team') ?? '',
  }
}

function readSplit(params: URLSearchParams): Split {
  const split = params.get('split')
  return SPLITS.some((s) => s.value === split) ? (split as Split) : 'team'
}

export function OverviewPage() {
  const [params, setParams] = useSearchParams()
  const [now] = useState(() => new Date())
  const filters = readFilters(params)
  const split = readSplit(params)
  const range = useMemo(
    () => resolveRange(filters.preset, now, filters.from, filters.to),
    [filters.preset, filters.from, filters.to, now],
  )
  const scope: LedgerFilters & { start: string; end: string } = {
    start: range.start,
    end: range.end,
    provider: (filters.provider || undefined) as Provider | undefined,
    team: filters.team || undefined,
  }

  const breakdown = useSpend(split === 'none' ? 'team' : split, scope)
  const teams = useSpend('team', { start: scope.start, end: scope.end, provider: scope.provider })
  const timeseries = useTimeseries(range.interval, split === 'none' ? null : split, scope)

  const teamOptions = useMemo(() => {
    const names = new Set(teams.data?.groups.map((g) => g.group) ?? [])
    if (filters.team) names.add(filters.team)
    return [...names].sort()
  }, [teams.data, filters.team])

  function update(next: Partial<Filters & { split: Split }>) {
    const merged = { ...filters, split, ...next }
    if (next.preset === 'custom' && !merged.from && !merged.to) {
      merged.from = utcDay(new Date(range.start))
      merged.to = utcDay(new Date(Date.parse(range.end) - 1))
    }
    const entries: [string, string][] = [
      ['range', merged.preset === '30d' ? '' : merged.preset],
      ['from', merged.preset === 'custom' ? merged.from : ''],
      ['to', merged.preset === 'custom' ? merged.to : ''],
      ['provider', merged.provider],
      ['team', merged.team],
      ['split', merged.split === 'team' ? '' : merged.split],
    ]
    setParams(new URLSearchParams(entries.filter(([, v]) => v)), { replace: true })
  }

  const stack = useMemo(
    () =>
      timeseries.data
        ? buildStack(timeseries.data.points, range.buckets, registryFor(split))
        : null,
    [timeseries.data, range.buckets, split],
  )
  const colorOf = useMemo(() => {
    if (!stack || split === 'none') return null
    const colors = new Map(stack.series.map((s) => [s.key, s.color]))
    const other = colors.get(OTHER)
    return (group: string) => colors.get(group) ?? other
  }, [stack, split])

  const error = breakdown.error ?? timeseries.error
  const total = breakdown.data?.total
  const refreshing = breakdown.isPlaceholderData || timeseries.isPlaceholderData
  const empty = total?.requests === 0

  return (
    <div className="overview">
      <div className="page-header">
        <h1>Overview</h1>
        <span className="muted">All times UTC</span>
      </div>
      <FilterBar
        filters={{ ...filters, preset: filters.preset as RangePreset }}
        teams={teamOptions}
        onChange={update}
      />

      {error && (
        <div className="notice notice-error" role="alert">
          Could not load spend data: {error.message}
        </div>
      )}

      <div
        className={refreshing ? 'overview-body refreshing' : 'overview-body'}
        aria-busy={refreshing}
      >
        {total ? <StatTiles total={total} /> : <div className="stats-placeholder" />}

        <section className="card" aria-labelledby="spend-chart-title">
          <div className="card-header">
            <h2 id="spend-chart-title">
              Spend per {range.interval}
              {split !== 'none' && <span className="muted"> by {split}</span>}
            </h2>
            <div className="segmented segmented-small" role="group" aria-label="Split chart by">
              {SPLITS.map((s) => (
                <button
                  key={s.value}
                  type="button"
                  className="segment"
                  aria-pressed={split === s.value}
                  onClick={() => update({ split: s.value })}
                >
                  {s.label}
                </button>
              ))}
            </div>
          </div>
          <div className="card-body">
            {empty ? (
              <EmptyState />
            ) : stack ? (
              <SpendChart rows={stack.rows} series={stack.series} interval={range.interval} />
            ) : (
              <div className="chart-placeholder" />
            )}
          </div>
        </section>

        {breakdown.data && !empty && (
          <section className="card" aria-labelledby="breakdown-title">
            <div className="card-header">
              <h2 id="breakdown-title">Breakdown by {split === 'none' ? 'team' : split}</h2>
            </div>
            <div className="card-body card-body-flush">
              <BreakdownTable report={breakdown.data} colorOf={colorOf} />
            </div>
          </section>
        )}
      </div>
    </div>
  )
}

function EmptyState() {
  return (
    <div className="empty-state">
      <p>
        <strong>No requests in this range.</strong>
      </p>
      <p className="secondary">
        Point an app at Tollbooth with a virtual key from the Keys page and its spend shows up here.
      </p>
    </div>
  )
}
