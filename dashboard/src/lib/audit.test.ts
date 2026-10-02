import type { AuditEvent } from '../api/types'
import { summarize } from './audit'

function event(details: Record<string, unknown>): AuditEvent {
  return {
    id: 'e',
    created_at: '2026-09-24T12:00:00Z',
    actor_type: 'session',
    actor_id: 'u',
    actor_label: 'ada@example.com',
    action: 'budget.updated',
    target_type: 'budget',
    target_id: 'b',
    details,
  }
}

describe('summarize', () => {
  it('leads with the name and lists changes', () => {
    expect(
      summarize(
        event({
          name: 'search',
          changes: {
            limit_usd: { from: '100', to: '250.5' },
            thresholds: { from: [50, 100], to: [] },
          },
        }),
      ),
    ).toBe('search · limit_usd: 100 → 250.5 · thresholds: 50, 100 → —')
  })

  it('shows remaining details as key: value', () => {
    expect(summarize(event({ email: 'x@y.co', address: '10.0.0.1', ok: false }))).toBe(
      'x@y.co · address: 10.0.0.1 · ok: false',
    )
    expect(summarize(event({}))).toBe('')
  })
})
