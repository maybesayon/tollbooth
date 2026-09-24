import {
  formatCompact,
  formatDateTimeUTC,
  formatInt,
  formatMs,
  formatPercent,
  formatUSD,
  formatUSDExact,
  formatUSDTick,
} from './format'

describe('formatUSD', () => {
  it.each([
    ['0', '$0.00'],
    ['0.0400956', '$0.0401'],
    ['0.000517801', '$0.000518'],
    ['0.000000001', '$0.000000001'],
    ['1', '$1.00'],
    ['1234.5678', '$1,234.57'],
    [null, '—'],
    ['not a number', '—'],
  ])('%s -> %s', (input, expected) => {
    expect(formatUSD(input)).toBe(expected)
  })
})

describe('formatUSDExact', () => {
  it('keeps every digit of the ledger value', () => {
    expect(formatUSDExact('0.000517801')).toBe('$0.000517801')
    expect(formatUSDExact(null)).toBe('unpriced')
  })
})

describe('number helpers', () => {
  it('formats counts', () => {
    expect(formatInt(1234567)).toBe('1,234,567')
    expect(formatCompact(1234567)).toBe('1.2M')
    expect(formatPercent(1, 8)).toBe('12.5%')
    expect(formatPercent(1, 0)).toBe('—')
  })

  it('formats latency', () => {
    expect(formatMs(null)).toBe('—')
    expect(formatMs(842)).toBe('842 ms')
    expect(formatMs(1534)).toBe('1.53 s')
    expect(formatMs(61_000)).toBe('61.0 s')
  })

  it('formats timestamps in UTC', () => {
    expect(formatDateTimeUTC('2026-09-01T12:15:03Z')).toBe('Sep 1, 12:15:03 PM UTC')
  })
})

describe('formatUSDTick', () => {
  it('uses cents at or above one cent', () => {
    expect(formatUSDTick(0)).toBe('$0')
    expect(formatUSDTick(0.8)).toBe('$0.80')
    expect(formatUSDTick(2.4)).toBe('$2.40')
    expect(formatUSDTick(0.0025)).toBe('$0.0025')
  })
})
