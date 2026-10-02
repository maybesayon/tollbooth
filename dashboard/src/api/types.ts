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

export type BudgetScopeType = 'global' | 'team' | 'key'
export type BudgetPeriod = 'day' | 'week' | 'month'
export type Enforcement = 'soft' | 'hard'

export interface BudgetScope {
  type: BudgetScopeType
  value: string | null
}

export interface Budget {
  id: string
  name: string
  scope: BudgetScope
  period: BudgetPeriod
  limit_usd: USD
  enforcement: Enforcement
  thresholds: number[]
  enabled: boolean
  channel_ids: string[]
  created_at: string
  updated_at: string
  usage: {
    period_start: string
    period_end: string
    spend_usd: USD
    percent_used: number
    exhausted: boolean
  }
}

export interface BudgetInput {
  name: string
  scope: BudgetScope
  period: BudgetPeriod
  limit_usd: string
  enforcement: Enforcement
  thresholds: number[]
  enabled: boolean
  channel_ids: string[]
}

export type ChannelType = 'webhook' | 'slack'

export interface AlertChannel {
  id: string
  name: string
  type: ChannelType
  url_hint: string
  created_at: string
}

export interface CreatedAlertChannel extends AlertChannel {
  signing_secret: string | null
}

export interface ChannelTestResult {
  ok: boolean
  status_code: number | null
  error: string | null
}

export type DeliveryStatus = 'pending' | 'delivered' | 'failed' | 'skipped'

export interface AlertDelivery {
  channel_id: string
  channel_name: string
  status: DeliveryStatus
  attempts: number
  last_error: string | null
  updated_at: string
}

export interface BudgetAlert {
  id: string
  budget_id: string
  budget_name: string
  threshold_percent: number
  spend_usd: USD
  limit_usd: USD
  period_start: string
  period_end: string
  created_at: string
  deliveries: AlertDelivery[]
}

export type Role = 'viewer' | 'editor' | 'admin'

export interface User {
  id: string
  email: string
  name: string
  role: Role
  active: boolean
  created_at: string
  last_login_at: string | null
  disabled_at: string | null
}

export interface Me {
  user: User | null
  role: Role
  via: 'session' | 'api_token' | 'admin_token'
}

export interface SetupStatus {
  needs_setup: boolean
  setup_with_admin_token: boolean
}

export interface ApiTokenInfo {
  id: string
  name: string
  prefix: string
  created_at: string
  last_used_at: string | null
}

export interface CreatedApiToken extends ApiTokenInfo {
  token: string
}

export interface CreatedUser extends User {
  temporary_password: string | null
}

export interface AuditEvent {
  id: string
  created_at: string
  actor_type: string
  actor_id: string | null
  actor_label: string
  action: string
  target_type: string | null
  target_id: string | null
  details: Record<string, unknown>
}
