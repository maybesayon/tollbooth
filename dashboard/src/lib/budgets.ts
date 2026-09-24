import type { Budget, BudgetPeriod, VirtualKey } from '../api/types'

export const PERIOD_LABELS: Record<BudgetPeriod, string> = {
  day: 'Daily',
  week: 'Weekly',
  month: 'Monthly',
}

export function scopeLabel(budget: Pick<Budget, 'scope'>, keys: Map<string, VirtualKey>): string {
  const { type, value } = budget.scope
  if (type === 'global') return 'All traffic'
  if (type === 'team') return `Team ${value}`
  const key = value ? keys.get(value) : undefined
  return key ? `Key ${key.name} (${key.team})` : `Key ${value?.slice(0, 8)}`
}

export type Severity = 'ok' | 'near' | 'over'

export function severity(percentUsed: number): Severity {
  if (percentUsed >= 100) return 'over'
  if (percentUsed >= 80) return 'near'
  return 'ok'
}

/** Parses "50, 80, 100" into sorted unique percents; null when anything is invalid. */
export function parseThresholds(text: string): number[] | null {
  const parts = text
    .split(/[\s,]+/)
    .map((p) => p.replace(/%$/, ''))
    .filter(Boolean)
  const values = parts.map(Number)
  if (values.some((v) => !Number.isInteger(v) || v < 1 || v > 1000) || values.length > 10) {
    return null
  }
  return [...new Set(values)].sort((a, b) => a - b)
}

/** A positive dollar amount with at most nine decimals, as the API requires. */
export function isValidLimit(text: string): boolean {
  return /^\d+(\.\d{1,9})?$/.test(text.trim()) && Number(text) > 0
}

const resetFormat = new Intl.DateTimeFormat('en-US', {
  month: 'short',
  day: 'numeric',
  timeZone: 'UTC',
})

export function resetLabel(periodEnd: string): string {
  return `Resets ${resetFormat.format(new Date(periodEnd))}`
}
