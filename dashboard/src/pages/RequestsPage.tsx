import { Fragment, useMemo, useState, type ReactNode } from 'react'
import { useSearchParams } from 'react-router'
import { useKeys, useRequestLog, useSpend } from '../api/queries'
import type { LedgerFilters, LedgerRequest, Outcome, Provider, VirtualKey } from '../api/types'
import { OutcomeBadge } from '../components/Badge'
import { ProviderName } from '../components/ProviderName'
import {
  formatCompact,
  formatDateTimeUTC,
  formatInt,
  formatMs,
  formatUSD,
  formatUSDExact,
} from '../lib/format'
import { OUTCOMES, PROVIDER_NAMES } from '../lib/labels'
import './RequestsPage.css'

const FILTER_KEYS = ['outcome', 'provider', 'team', 'model'] as const

export function RequestsPage() {
  const [params, setParams] = useSearchParams()
  const filters: LedgerFilters = {
    outcome: (params.get('outcome') as Outcome | null) ?? undefined,
    provider: (params.get('provider') as Provider | null) ?? undefined,
    team: params.get('team') ?? undefined,
    model: params.get('model') ?? undefined,
  }
  const log = useRequestLog(filters)
  const keys = useKeys(true)
  const teams = useSpend('team', {})
  const models = useSpend('model', {})

  const keysById = useMemo(() => new Map((keys.data ?? []).map((k) => [k.id, k])), [keys.data])
  const items = log.data?.pages.flatMap((p) => p.items) ?? []
  const refreshing = log.isPlaceholderData

  function setFilter(key: (typeof FILTER_KEYS)[number], value: string) {
    const next = new URLSearchParams(params)
    if (value) next.set(key, value)
    else next.delete(key)
    setParams(next, { replace: true })
  }

  const active = FILTER_KEYS.some((k) => params.get(k))

  return (
    <div className="page">
      <div className="page-header">
        <h1>Requests</h1>
        <span className="muted">Metadata only; prompts and responses are never stored</span>
      </div>

      <div className="filter-bar" role="group" aria-label="Filters">
        <FilterSelect
          label="Outcome"
          value={filters.outcome ?? ''}
          all="All outcomes"
          options={Object.entries(OUTCOMES).map(([value, o]) => [value, o.label])}
          onChange={(v) => setFilter('outcome', v)}
        />
        <FilterSelect
          label="Provider"
          value={filters.provider ?? ''}
          all="All providers"
          options={Object.entries(PROVIDER_NAMES)}
          onChange={(v) => setFilter('provider', v)}
        />
        <FilterSelect
          label="Team"
          value={filters.team ?? ''}
          all="All teams"
          options={withSelected(
            teams.data?.groups.map((g) => g.group),
            filters.team,
          )}
          onChange={(v) => setFilter('team', v)}
        />
        <FilterSelect
          label="Model"
          value={filters.model ?? ''}
          all="All models"
          options={withSelected(
            models.data?.groups.map((g) => g.group),
            filters.model,
          )}
          onChange={(v) => setFilter('model', v)}
        />
        {active && (
          <button
            type="button"
            className="button button-ghost"
            onClick={() => setParams(new URLSearchParams(), { replace: true })}
          >
            Clear filters
          </button>
        )}
      </div>

      {log.error && (
        <div className="notice notice-error" role="alert">
          Could not load requests: {log.error.message}
        </div>
      )}

      <section className={refreshing ? 'card refreshing' : 'card'} aria-busy={refreshing}>
        {log.data && items.length === 0 ? (
          <div className="card-body">
            <p className="secondary">
              {active ? 'No requests match these filters.' : 'No requests recorded yet.'}
            </p>
          </div>
        ) : (
          <div className="table-wrap">
            <table className="table requests-table">
              <thead>
                <tr>
                  <th scope="col">Time (UTC)</th>
                  <th scope="col">Team</th>
                  <th scope="col">Key</th>
                  <th scope="col">Model</th>
                  <th scope="col">Outcome</th>
                  <th scope="col" className="num">
                    Tokens in / out
                  </th>
                  <th scope="col" className="num">
                    Cost
                  </th>
                  <th scope="col" className="num">
                    Latency
                  </th>
                </tr>
              </thead>
              <tbody>
                {items.map((request) => (
                  <RequestRow
                    key={request.id}
                    request={request}
                    vkey={keysById.get(request.key_id)}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {log.hasNextPage && (
        <button
          type="button"
          className="button load-more"
          disabled={log.isFetchingNextPage}
          onClick={() => void log.fetchNextPage()}
        >
          {log.isFetchingNextPage ? 'Loading…' : 'Load more'}
        </button>
      )}
    </div>
  )
}

function withSelected(options: string[] | undefined, selected: string | undefined) {
  const names = new Set(options ?? [])
  if (selected) names.add(selected)
  return [...names].sort().map((name): [string, string] => [name, name])
}

interface FilterSelectProps {
  label: string
  value: string
  all: string
  options: [string, string][]
  onChange: (value: string) => void
}

function FilterSelect({ label, value, all, options, onChange }: FilterSelectProps) {
  const id = `filter-${label.toLowerCase()}`
  return (
    <>
      <label className="visually-hidden" htmlFor={id}>
        {label}
      </label>
      <select id={id} className="select" value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">{all}</option>
        {options.map(([v, text]) => (
          <option key={v} value={v}>
            {text}
          </option>
        ))}
      </select>
    </>
  )
}

function RequestRow({ request, vkey }: { request: LedgerRequest; vkey: VirtualKey | undefined }) {
  const [open, setOpen] = useState(false)
  const tokensIn = request.input_tokens + request.cache_read_tokens + request.cache_write_tokens
  return (
    <Fragment>
      <tr className={open ? 'request-row open' : 'request-row'}>
        <td>
          <button
            type="button"
            className="row-toggle"
            aria-expanded={open}
            onClick={() => setOpen(!open)}
          >
            <span className="chevron" aria-hidden="true" />
            <span className="numeric">
              {formatDateTimeUTC(request.created_at).replace(' UTC', '')}
            </span>
          </button>
        </td>
        <td>{request.team}</td>
        <td className="secondary">
          {vkey ? vkey.name : <code>{request.key_id.slice(0, 8)}</code>}
        </td>
        <td>
          <code>{request.model}</code>
        </td>
        <td>
          <OutcomeBadge outcome={request.outcome} />
        </td>
        <td className="num">
          {formatCompact(tokensIn)} / {formatCompact(request.output_tokens)}
        </td>
        <td className="num" title={formatUSDExact(request.cost_usd)}>
          {request.cost_usd === null ? (
            <span className="muted">unpriced</span>
          ) : (
            formatUSD(request.cost_usd)
          )}
        </td>
        <td className="num">{formatMs(request.latency_ms)}</td>
      </tr>
      {open && (
        <tr className="request-details">
          <td colSpan={8}>
            <dl className="details-grid">
              <Detail label="Provider">
                <ProviderName provider={request.provider} />
              </Detail>
              <Detail label="HTTP status">{String(request.status_code)}</Detail>
              <Detail label="Streamed">{request.streamed ? 'Yes' : 'No'}</Detail>
              <Detail label="Time to first byte">{formatMs(request.ttfb_ms)}</Detail>
              <Detail label="Input tokens">{formatInt(request.input_tokens)}</Detail>
              <Detail label="Cache read">{formatInt(request.cache_read_tokens)}</Detail>
              <Detail label="Cache write">{formatInt(request.cache_write_tokens)}</Detail>
              <Detail label="Output tokens">{formatInt(request.output_tokens)}</Detail>
              <Detail label="Exact cost">{formatUSDExact(request.cost_usd)}</Detail>
              <Detail label="Error type">{request.error_type ?? '—'}</Detail>
              <Detail label="Upstream request ID">
                {request.upstream_request_id ? <code>{request.upstream_request_id}</code> : '—'}
              </Detail>
              <Detail label="Ledger ID">
                <code>{request.id}</code>
              </Detail>
            </dl>
          </td>
        </tr>
      )}
    </Fragment>
  )
}

function Detail({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{children}</dd>
    </div>
  )
}
