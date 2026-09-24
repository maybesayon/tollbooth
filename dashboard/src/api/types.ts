export type Provider = 'openai' | 'anthropic'
export type GroupBy = 'team' | 'model' | 'provider' | 'key'
export type Interval = 'day' | 'hour'
export type Outcome =
  | 'success'
  | 'upstream_error'
  | 'upstream_unreachable'
  | 'client_disconnected'
  | 'proxy_error'
  | 'budget_exceeded'

/** USD amounts arrive as exact fixed-point decimal strings. */
export type USD = string

export interface Credential {
  id: string
  name: string
  provider: Provider
  created_at: string
}

export interface VirtualKey {
  id: string
  name: string
  team: string
  key_prefix: string
  provider: Provider
  credential_id: string
  created_at: string
  revoked_at: string | null
}

export interface CreatedKey extends VirtualKey {
  key: string
}

export interface Metrics {
  requests: number
  input_tokens: number
  output_tokens: number
  cache_read_tokens: number
  cache_write_tokens: number
  cost_usd: USD
  unpriced_requests: number
  error_requests: number
}

export interface SpendGroup extends Metrics {
  group: string
}

export interface SpendReport {
  group_by: GroupBy
  start: string | null
  end: string | null
  currency: 'USD'
  total: Metrics
  groups: SpendGroup[]
}

export interface TimeseriesPoint extends Metrics {
  bucket: string
  group: string | null
}

export interface TimeseriesReport {
  interval: Interval
  group_by: GroupBy | null
  start: string
  end: string
  currency: 'USD'
  points: TimeseriesPoint[]
}

export interface LedgerRequest {
  id: string
  created_at: string
  team: string
  key_id: string
  provider: Provider
  model: string
  streamed: boolean
  status_code: number
  outcome: Outcome
  latency_ms: number
  ttfb_ms: number | null
  input_tokens: number
  output_tokens: number
  cache_read_tokens: number
  cache_write_tokens: number
  cost_usd: USD | null
  error_type: string | null
  upstream_request_id: string | null
}

export interface RequestPage {
  items: LedgerRequest[]
  next_cursor: string | null
}

export interface LedgerFilters {
  start?: string
  end?: string
  team?: string
  provider?: Provider
  model?: string
  key_id?: string
  outcome?: Outcome
}
