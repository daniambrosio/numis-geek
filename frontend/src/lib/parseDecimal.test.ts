import { describe, expect, it } from 'vitest'
import { parseDecimal } from './parseDecimal'

describe('parseDecimal', () => {
  it('parses US-style decimal (single dot, ≠3 dp)', () => {
    expect(parseDecimal('9911.26')).toBe(9911.26)
  })
  it('parses pt-BR decimal with comma', () => {
    expect(parseDecimal('9911,26')).toBe(9911.26)
  })
  it('parses pt-BR with thousand separator', () => {
    expect(parseDecimal('9.911,26')).toBe(9911.26)
    expect(parseDecimal('1.234.567,89')).toBe(1234567.89)
  })
  it('parses US with thousand separator', () => {
    expect(parseDecimal('9,911.26')).toBe(9911.26)
    expect(parseDecimal('1,234,567.89')).toBe(1234567.89)
  })
  it('treats repeated dots as thousands (no decimal part)', () => {
    expect(parseDecimal('1.234.567')).toBe(1234567)
  })
  it('treats repeated commas as thousands (no decimal part)', () => {
    expect(parseDecimal('1,234,567')).toBe(1234567)
  })
  it('plain integer', () => {
    expect(parseDecimal('850000')).toBe(850000)
  })
  it('trims whitespace', () => {
    expect(parseDecimal('  42,5  ')).toBe(42.5)
  })
  it('regression: 850000.00 (US style with .00 cents)', () => {
    expect(parseDecimal('850000.00')).toBe(850000)
  })
  it('regression: single-dot 3dp like 1.234 is treated as decimal', () => {
    // Typing 1.234 in pt-BR would normally use comma; the safer default
    // for free-typed input is decimal, not thousand-sep.
    expect(parseDecimal('1.234')).toBe(1.234)
  })
  it('empty / blank returns null', () => {
    expect(parseDecimal('')).toBeNull()
    expect(parseDecimal('   ')).toBeNull()
  })
  it('garbage returns null', () => {
    expect(parseDecimal('abc')).toBeNull()
  })
  it('negative numbers parse (caller validates sign)', () => {
    expect(parseDecimal('-5,50')).toBe(-5.5)
  })
})
