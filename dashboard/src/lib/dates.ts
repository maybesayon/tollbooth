import type { Interval } from '../api/types'

export type RangePreset = '7d' | '30d' | '90d' | 'custom'

export const PRESETS: { value: Exclude<RangePreset, 'custom'>; days: number }[] = [
  { value: '7d', days: 7 },
  { value: '30d', days: 30 },
  { value: '90d', days: 90 },
]

export interface DateRange {
  /** Inclusive UTC start (ISO). */
  start: string
  /** Exclusive UTC end (ISO). */
  end: string
  interval: Interval
  /** Every bucket start in the range, in the backend's ISO format. */
  buckets: string[]
}

const DAY_MS = 86_400_000
const HOUR_MS = 3_600_000

export function utcDay(date: Date): string {
  return date.toISOString().slice(0, 10)
}

/** Whole UTC days. Custom `from`/`to` are inclusive calendar dates (YYYY-MM-DD). */
export function resolveRange(
  preset: RangePreset,
  now: Date,
  from?: string | null,
  to?: string | null,
): DateRange {
  let startMs: number
  let endMs: number
  const tomorrow = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate() + 1)
  if (preset === 'custom' && from && to && isDay(from) && isDay(to) && from <= to) {
    startMs = Date.parse(`${from}T00:00:00Z`)
    endMs = Date.parse(`${to}T00:00:00Z`) + DAY_MS
  } else {
    const days = PRESETS.find((p) => p.value === preset)?.days ?? 30
    endMs = tomorrow
    startMs = endMs - days * DAY_MS
  }
  const interval: Interval = endMs - startMs <= 2 * DAY_MS ? 'hour' : 'day'
  const step = interval === 'hour' ? HOUR_MS : DAY_MS
  const buckets: string[] = []
  for (let t = startMs; t < endMs; t += step) buckets.push(isoSeconds(t))
  return { start: isoSeconds(startMs), end: isoSeconds(endMs), interval, buckets }
}

function isDay(value: string): boolean {
  return /^\d{4}-\d{2}-\d{2}$/.test(value) && !Number.isNaN(Date.parse(`${value}T00:00:00Z`))
}

function isoSeconds(ms: number): string {
  return new Date(ms).toISOString().replace('.000Z', 'Z')
}

const dayLabel = new Intl.DateTimeFormat('en-US', {
  month: 'short',
  day: 'numeric',
  timeZone: 'UTC',
})
const hourLabel = new Intl.DateTimeFormat('en-US', { hour: 'numeric', timeZone: 'UTC' })

export function bucketLabel(bucket: string, interval: Interval): string {
  const date = new Date(bucket)
  return interval === 'hour' ? hourLabel.format(date) : dayLabel.format(date)
}

export function bucketTitle(bucket: string, interval: Interval): string {
  const date = new Date(bucket)
  if (interval === 'day') return `${dayLabel.format(date)} (UTC)`
  return `${dayLabel.format(date)}, ${hourLabel.format(date)} (UTC)`
}
