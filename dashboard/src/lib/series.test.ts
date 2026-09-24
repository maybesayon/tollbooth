import { metrics } from '../test/fakeApi'
import { ColorRegistry, OTHER, buildStack } from './series'

const BUCKETS = ['2026-09-01T00:00:00Z', '2026-09-02T00:00:00Z', '2026-09-03T00:00:00Z']

function point(bucket: string, group: string | null, cost: string) {
  return { ...metrics({ cost_usd: cost, requests: 1 }), bucket, group }
}

describe('buildStack', () => {
  it('zero-fills missing buckets and ranks series by spend', () => {
    const { rows, series } = buildStack(
      [
        point(BUCKETS[0]!, 'ads', '0.5'),
        point(BUCKETS[0]!, 'search', '1.25'),
        point(BUCKETS[2]!, 'ads', '0.25'),
      ],
      BUCKETS,
      new ColorRegistry(),
    )
    expect(series.map((s) => s.key)).toEqual(['search', 'ads'])
    expect(rows).toEqual([
      { bucket: BUCKETS[0], search: 1.25, ads: 0.5 },
      { bucket: BUCKETS[1], search: 0, ads: 0 },
      { bucket: BUCKETS[2], search: 0, ads: 0.25 },
    ])
  })

  it('folds everything past the top six into Other', () => {
    const points = Array.from({ length: 9 }, (_, i) => point(BUCKETS[0]!, `team-${i}`, `${9 - i}`))
    const { rows, series } = buildStack(points, BUCKETS, new ColorRegistry())
    expect(series).toHaveLength(7)
    expect(series.at(-1)).toEqual({ key: OTHER, color: 'var(--series-other)' })
    expect(rows[0]?.[OTHER]).toBe(3 + 2 + 1)
  })

  it('labels an ungrouped series as Total', () => {
    const { series } = buildStack([point(BUCKETS[0]!, null, '1')], BUCKETS, new ColorRegistry())
    expect(series.map((s) => s.key)).toEqual(['Total'])
  })
})

describe('ColorRegistry', () => {
  it('keeps an entity on its slot when others disappear', () => {
    const colors = new ColorRegistry()
    expect(colors.colorFor('a')).toBe('var(--series-1)')
    expect(colors.colorFor('b')).toBe('var(--series-2)')
    expect(colors.colorFor('b')).toBe('var(--series-2)')
    expect(colors.colorFor('c')).toBe('var(--series-3)')
  })

  it('never generates an eighth hue', () => {
    const colors = new ColorRegistry()
    for (let i = 0; i < 7; i++) colors.colorFor(`t${i}`)
    expect(colors.colorFor('t7')).toBe('var(--series-other)')
  })
})
