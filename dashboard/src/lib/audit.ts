import type { AuditEvent } from '../api/types'

/** One readable line; values are rendered as text, never HTML. */
export function summarize(event: AuditEvent): string {
  const { details } = event
  const changes = details.changes as Record<string, { from: unknown; to: unknown }> | undefined
  const parts: string[] = []
  const label = details.name ?? details.email
  if (typeof label === 'string') parts.push(label)
  if (changes) {
    for (const [field, change] of Object.entries(changes)) {
      parts.push(`${field}: ${show(change.from)} → ${show(change.to)}`)
    }
  }
  for (const [key, value] of Object.entries(details)) {
    if (['name', 'email', 'changes'].includes(key)) continue
    parts.push(`${key}: ${show(value)}`)
  }
  return parts.join(' · ')
}

function show(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (Array.isArray(value)) return value.join(', ') || '—'
  return String(value)
}
