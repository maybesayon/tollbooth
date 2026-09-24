import { bucketLabel, bucketTitle, resolveRange } from './dates'

const NOW = new Date('2026-09-24T15:30:00Z')

describe('resolveRange', () => {
  it('covers whole UTC days up to and including today', () => {
    const range = resolveRange('7d', NOW)
    expect(range.start).toBe('2026-09-18T00:00:00Z')
    expect(range.end).toBe('2026-09-25T00:00:00Z')
    expect(range.interval).toBe('day')
    expect(range.buckets).toHaveLength(7)
    expect(range.buckets[0]).toBe('2026-09-18T00:00:00Z')
    expect(range.buckets.at(-1)).toBe('2026-09-24T00:00:00Z')
  })

  it('treats custom dates as inclusive', () => {
    const range = resolveRange('custom', NOW, '2026-09-01', '2026-09-10')
    expect(range.start).toBe('2026-09-01T00:00:00Z')
    expect(range.end).toBe('2026-09-11T00:00:00Z')
    expect(range.buckets).toHaveLength(10)
  })

  it('switches to hourly buckets for ranges of two days or less', () => {
    const range = resolveRange('custom', NOW, '2026-09-20', '2026-09-20')
    expect(range.interval).toBe('hour')
    expect(range.buckets).toHaveLength(24)
    expect(range.buckets[13]).toBe('2026-09-20T13:00:00Z')
  })

  it.each([
    ['2026-09-10', '2026-09-01'],
    ['garbage', '2026-09-01'],
    [null, null],
  ])('falls back to 30 days for an invalid custom range (%s..%s)', (from, to) => {
    const range = resolveRange('custom', NOW, from, to)
    expect(range.buckets).toHaveLength(30)
  })
})

describe('bucket labels', () => {
  it('formats in UTC', () => {
    expect(bucketLabel('2026-09-01T00:00:00Z', 'day')).toBe('Sep 1')
    expect(bucketLabel('2026-09-01T13:00:00Z', 'hour')).toBe('1 PM')
    expect(bucketTitle('2026-09-01T13:00:00Z', 'hour')).toBe('Sep 1, 1 PM (UTC)')
  })
})
