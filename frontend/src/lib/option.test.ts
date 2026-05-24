import { describe, expect, it } from 'vitest'
import {
  daysToExpiration, distanceToStrike, effectivePrice, isITM,
} from './option'

describe('isITM', () => {
  it('PUT is ITM when price < strike', () => {
    expect(isITM('PUT', 40, 35)).toBe(true)
  })
  it('PUT is OTM when price > strike', () => {
    expect(isITM('PUT', 40, 42)).toBe(false)
  })
  it('CALL is ITM when price > strike', () => {
    expect(isITM('CALL', 40, 45)).toBe(true)
  })
  it('CALL is OTM when price < strike', () => {
    expect(isITM('CALL', 40, 38)).toBe(false)
  })
})

describe('distanceToStrike', () => {
  it('positive when price above strike', () => {
    expect(distanceToStrike(100, 110)).toBeCloseTo(0.1, 4)
  })
  it('negative when price below strike', () => {
    expect(distanceToStrike(100, 90)).toBeCloseTo(-0.1, 4)
  })
  it('zero when price equals strike', () => {
    expect(distanceToStrike(50, 50)).toBe(0)
  })
  it('returns 0 when strike is 0 to avoid division by zero', () => {
    expect(distanceToStrike(0, 50)).toBe(0)
  })
})

describe('effectivePrice', () => {
  it('PUT short: strike minus premium', () => {
    // Sold PUT at 36.40 strike, received 1.40/share premium.
    // Effective buy price if exercised = 36.40 - 1.40 = 35.00
    expect(effectivePrice('PUT', 36.40, 1.40)).toBeCloseTo(35.00, 2)
  })
  it('CALL short: strike plus premium', () => {
    // Sold CALL at 47.50 strike, received 0.80/share premium.
    // Effective sell price if exercised = 47.50 + 0.80 = 48.30
    expect(effectivePrice('CALL', 47.50, 0.80)).toBeCloseTo(48.30, 2)
  })
  it('uses absolute premium (handles negative inputs)', () => {
    expect(effectivePrice('PUT', 36.40, -1.40)).toBeCloseTo(35.00, 2)
  })
})

describe('daysToExpiration', () => {
  const today = new Date('2026-05-24T00:00:00Z')
  it('counts whole days forward', () => {
    expect(daysToExpiration('2026-06-19T00:00:00Z', today)).toBe(26)
  })
  it('clamps past dates to 0', () => {
    expect(daysToExpiration('2026-04-01T00:00:00Z', today)).toBe(0)
  })
  it('returns 0 for same day', () => {
    expect(daysToExpiration('2026-05-24T00:00:00Z', today)).toBe(0)
  })
})
