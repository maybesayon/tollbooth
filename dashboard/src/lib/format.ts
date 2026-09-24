import type { USD } from '../api/types'

const usdLarge = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})
const usdSmall = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  maximumSignificantDigits: 3,
})
const integer = new Intl.NumberFormat('en-US')
const compact = new Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 1 })
const percent = new Intl.NumberFormat('en-US', { style: 'percent', maximumFractionDigits: 1 })

/** Dollars at a readable precision: cents from $1, three significant digits below. */
export function formatUSD(value: USD | number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  const amount = typeof value === 'number' ? value : Number(value)
  if (!Number.isFinite(amount)) return '—'
  if (amount === 0) return '$0.00'
  return Math.abs(amount) >= 1 ? usdLarge.format(amount) : usdSmall.format(amount)
}

/** Axis ticks: cents whenever the value is at least a cent, so a scale reads $0.80 not $0.8. */
export function formatUSDTick(value: number): string {
  if (value === 0) return '$0'
  return Math.abs(value) >= 0.01 ? usdLarge.format(value) : usdSmall.format(value)
}

/** Full precision, for tooltips and titles where the exact ledger value matters. */
export function formatUSDExact(value: USD | null | undefined): string {
  if (value === null || value === undefined) return 'unpriced'
  return value.startsWith('-') ? `-$${value.slice(1)}` : `$${value}`
}

export function formatInt(value: number): string {
  return integer.format(value)
}

export function formatCompact(value: number): string {
  return compact.format(value)
}

export function formatPercent(part: number, whole: number): string {
  return whole === 0 ? '—' : percent.format(part / whole)
}

export function formatMs(ms: number | null): string {
  if (ms === null) return '—'
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(ms < 10_000 ? 2 : 1)} s`
}

const dateTime = new Intl.DateTimeFormat('en-US', {
  month: 'short',
  day: 'numeric',
  hour: 'numeric',
  minute: '2-digit',
  second: '2-digit',
  timeZone: 'UTC',
})

export function formatDateTimeUTC(iso: string): string {
  return `${dateTime.format(new Date(iso))} UTC`
}

const date = new Intl.DateTimeFormat('en-US', {
  year: 'numeric',
  month: 'short',
  day: 'numeric',
  timeZone: 'UTC',
})

export function formatDateUTC(iso: string): string {
  return date.format(new Date(iso))
}
