import { describe, expect, it } from 'vitest'
import { fmtBRL, fmtMoney, fmtUSD } from './money'

describe('fmtBRL compact', () => {
  it('milhão usa M', () => {
    expect(fmtBRL(12_800_000, { compact: true })).toBe('R$ 12,8M')
    expect(fmtBRL(1_000_000, { compact: true })).toBe('R$ 1,0M')
  })
  it('mil usa k', () => {
    expect(fmtBRL(11_800, { compact: true })).toBe('R$ 11,8k')
    // <660 cai no fallback (Intl.NumberFormat, usa NBSP)
    expect(fmtBRL(660, { compact: true }).replace(/ /g, ' ')).toBe('R$ 660')
  })
  it('negativo', () => {
    expect(fmtBRL(-2_500, { compact: true })).toBe('-R$ 2,5k')
  })
  it('valor padrão', () => {
    expect(fmtBRL(12.5).replace(/ /g, ' ')).toBe('R$ 12,50')
  })
})

describe('fmtUSD compact', () => {
  it('milhão usa M', () => {
    expect(fmtUSD(2_600_000, { compact: true })).toBe('US$ 2,6M')
  })
  it('mil usa k', () => {
    expect(fmtUSD(133_100, { compact: true })).toBe('US$ 133,1k')
  })
})

describe('fmtMoney', () => {
  it('roteia BRL/USD', () => {
    expect(fmtMoney(5_000, 'BRL', { compact: true })).toBe('R$ 5,0k')
    expect(fmtMoney(5_000, 'USD', { compact: true })).toBe('US$ 5,0k')
  })
})
