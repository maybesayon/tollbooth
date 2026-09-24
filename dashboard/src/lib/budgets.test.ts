import type { VirtualKey } from '../api/types'
import { isValidLimit, parseThresholds, resetLabel, scopeLabel, severity } from './budgets'

describe('budget helpers', () => {
  it('parses thresholds', () => {
    expect(parseThresholds('80, 50 100%')).toEqual([50, 80, 100])
    expect(parseThresholds('50,50')).toEqual([50])
    expect(parseThresholds('')).toEqual([])
    expect(parseThresholds('0')).toBeNull()
    expect(parseThresholds('12.5')).toBeNull()
    expect(parseThresholds('abc')).toBeNull()
    expect(parseThresholds('1 2 3 4 5 6 7 8 9 10 11')).toBeNull()
  })

  it('validates limits', () => {
    expect(isValidLimit('100')).toBe(true)
    expect(isValidLimit('0.000000001')).toBe(true)
    expect(isValidLimit('0')).toBe(false)
    expect(isValidLimit('0.0000000001')).toBe(false)
    expect(isValidLimit('-5')).toBe(false)
    expect(isValidLimit('1e3')).toBe(false)
  })

  it('grades severity', () => {
    expect(severity(79.9)).toBe('ok')
    expect(severity(80)).toBe('near')
    expect(severity(100)).toBe('over')
  })

  it('describes scopes', () => {
    const keys = new Map([['k1', { id: 'k1', name: 'svc', team: 'ads' } as VirtualKey]])
    expect(scopeLabel({ scope: { type: 'global', value: null } }, keys)).toBe('All traffic')
    expect(scopeLabel({ scope: { type: 'team', value: 'search' } }, keys)).toBe('Team search')
    expect(scopeLabel({ scope: { type: 'key', value: 'k1' } }, keys)).toBe('Key svc (ads)')
    expect(scopeLabel({ scope: { type: 'key', value: 'abcdef123456' } }, keys)).toBe('Key abcdef12')
  })

  it('labels resets in UTC', () => {
    expect(resetLabel('2026-10-01T00:00:00Z')).toBe('Resets Oct 1')
  })
})
