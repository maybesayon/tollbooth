import type { Me, Metrics, Role, SpendReport, TimeseriesReport } from '../api/types'

type Handler = (url: URL, init: RequestInit) => unknown
export type Routes = Record<string, unknown>

/** A route response with its own status code. */
export class Reply {
  readonly status: number
  readonly body: unknown

  constructor(status: number, body: unknown = null) {
    this.status = status
    this.body = body
  }
}

export function me(role: Role = 'admin'): Me {
  return {
    user: {
      id: 'u1',
      email: `${role}@example.com`,
      name: `Ada ${role}`,
      role,
      active: true,
      created_at: '2026-09-01T00:00:00Z',
      last_login_at: null,
      disabled_at: null,
    },
    role,
    via: 'session',
  }
}

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
      const result = typeof route === 'function' ? (route as Handler)(url, init) : route
      if (result instanceof Reply) {
        if (result.status === 204) return new Response(null, { status: 204 })
        return new Response(JSON.stringify(result.body), { status: result.status })
      }
      if (result === null && init.method === 'DELETE') return new Response(null, { status: 204 })
      return new Response(JSON.stringify(result), { status })
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

export const SIGNED_OUT: Routes = {
  '/auth/me': new Reply(401, { detail: 'authentication required' }),
  '/auth/setup': { needs_setup: false, setup_with_admin_token: true },
}

export const EMPTY_ROUTES: Routes = {
  '/auth/me': me('admin'),
  '/auth/setup': { needs_setup: false, setup_with_admin_token: true },
  '/auth/logout': new Reply(204),
  '/admin/credentials': [],
  '/admin/keys': [],
  '/admin/spend': spendReport(),
  '/admin/spend/timeseries': timeseries(),
  '/admin/requests': { items: [], next_cursor: null },
}
