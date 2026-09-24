import type { Outcome, Provider } from '../api/types'

export type Tone = 'good' | 'warning' | 'serious' | 'critical' | 'neutral'

export const PROVIDER_NAMES: Record<Provider, string> = {
  openai: 'OpenAI',
  anthropic: 'Anthropic',
}

export const OUTCOMES: Record<Outcome, { tone: Tone; label: string }> = {
  success: { tone: 'good', label: 'Success' },
  upstream_error: { tone: 'critical', label: 'Upstream error' },
  upstream_unreachable: { tone: 'critical', label: 'Unreachable' },
  client_disconnected: { tone: 'warning', label: 'Client left' },
  proxy_error: { tone: 'serious', label: 'Proxy error' },
}
