import type { TimeseriesPoint } from '../api/types'

export const MAX_SERIES = 7
export const OTHER = 'Other'
export const TOTAL = 'Total'

export interface Series {
  key: string
  color: string
}

export type StackRow = { bucket: string } & Record<string, number | string>

/**
 * Color slots follow the entity, not its rank: once a name has a slot it keeps it for the
 * session, so filtering never repaints the survivors. Slots are handed out in the order names
 * are first seen, which callers make spend-descending.
 */
export class ColorRegistry {
  private readonly slots = new Map<string, number>()

  colorFor(name: string): string {
    let slot = this.slots.get(name)
    if (slot === undefined) {
      slot = this.slots.size + 1
      this.slots.set(name, slot)
    }
    return slot <= MAX_SERIES ? `var(--series-${slot})` : 'var(--series-other)'
  }
}

/**
 * Pivot timeseries points into one row per bucket (zero-filled), keeping the top groups by
 * total spend and folding the rest into "Other".
 */
export function buildStack(
  points: TimeseriesPoint[],
  buckets: string[],
  colors: ColorRegistry,
): { rows: StackRow[]; series: Series[] } {
  const totals = new Map<string, number>()
  for (const p of points) {
    const name = p.group ?? TOTAL
    totals.set(name, (totals.get(name) ?? 0) + Number(p.cost_usd))
  }
  const ranked = [...totals.entries()]
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .map(([name]) => name)
  const needsOther = ranked.length > MAX_SERIES
  const kept = needsOther ? ranked.slice(0, MAX_SERIES - 1) : ranked
  const keptSet = new Set(kept)

  const byBucket = new Map<string, StackRow>()
  for (const bucket of buckets) {
    const row: StackRow = { bucket }
    for (const name of kept) row[name] = 0
    if (needsOther) row[OTHER] = 0
    byBucket.set(bucket, row)
  }
  for (const p of points) {
    const row = byBucket.get(p.bucket)
    if (!row) continue
    const name = p.group ?? TOTAL
    const key = keptSet.has(name) ? name : OTHER
    row[key] = (row[key] as number) + Number(p.cost_usd)
  }

  const series: Series[] = kept.map((key) => ({ key, color: colors.colorFor(key) }))
  if (needsOther) series.push({ key: OTHER, color: 'var(--series-other)' })
  return { rows: [...byBucket.values()], series }
}
