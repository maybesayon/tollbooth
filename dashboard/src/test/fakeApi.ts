import type { Metrics, SpendReport, TimeseriesReport } from '../api/types'

type Handler = (url: URL, init: RequestInit) => unknown
export type Routes = Record<string, unknown>

export interface FakeApi {
  calls: { url: URL; init: RequestInit }[]
  paramsFor: (path: string) => URLSearchParams[]
}

/** Stubs fetch with per-path JSON responses. A route value may be a function of the request. */
export function fakeApi(routes: Routes, status = 200): FakeApi {
  const calls: FakeApi['calls'] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: string, init: RequestInit = {}) => {
      const url = new URL(input, 'http://tollbooth.test')
      calls.push({ url, init })
      const route = routes[url.pathname]
      if (route === undefined) return new Response('{"detail":"not found"}', { status: 404 })
      const body = typeof route === 'function' ? (route as Handler)(url, init) : route
      return new Response(JSON.stringify(body), { status })
    }),
  )
  return {
    calls,
    paramsFor: (path) =>
      calls.filter((c) => c.url.pathname === path).map((c) => c.url.searchParams),
  }
}

export function metrics(overrides: Partial<Metrics> = {}): Metrics {
  return {
    requests: 0,
    input_tokens: 0,
    output_tokens: 0,
    cache_read_tokens: 0,
    cache_write_tokens: 0,
    cost_usd: '0',
    unpriced_requests: 0,
    error_requests: 0,
    ...overrides,
  }
}

export function spendReport(groups: SpendReport['groups'] = []): SpendReport {
  const sum = (k: keyof Omit<Metrics, 'cost_usd'>) => groups.reduce((n, g) => n + g[k], 0)
  return {
    group_by: 'team',
    start: null,
    end: null,
    currency: 'USD',
    total: metrics({
      requests: sum('requests'),
      input_tokens: sum('input_tokens'),
      output_tokens: sum('output_tokens'),
      error_requests: sum('error_requests'),
      unpriced_requests: sum('unpriced_requests'),
      cost_usd: String(groups.reduce((n, g) => n + Number(g.cost_usd), 0)),
    }),
    groups,
  }
}

export function timeseries(points: TimeseriesReport['points'] = []): TimeseriesReport {
  return { interval: 'day', group_by: 'team', start: '', end: '', currency: 'USD', points }
}

export const EMPTY_ROUTES: Routes = {
  '/admin/credentials': [],
  '/admin/keys': [],
  '/admin/spend': spendReport(),
  '/admin/spend/timeseries': timeseries(),
  '/admin/requests': { items: [], next_cursor: null },
}
