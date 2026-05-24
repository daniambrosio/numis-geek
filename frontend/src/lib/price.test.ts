import { describe, expect, it } from 'vitest'
import {
  TIER_COLOR, SOURCE_LABEL, AUTOMATED_SOURCES,
  formatRelative, aggregatePriceStats,
} from './price'
import type { AssetOut } from './api'

describe('TIER_COLOR', () => {
  it('uses green for FRESH, amber for STALE, red for OLD, slate for UNKNOWN', () => {
    expect(TIER_COLOR.FRESH).toBe('#22c55e')
    expect(TIER_COLOR.STALE).toBe('#f59e0b')
    expect(TIER_COLOR.OLD).toBe('#ef4444')
    expect(TIER_COLOR.UNKNOWN).toBe('#94a3b8')
  })
})

describe('SOURCE_LABEL', () => {
  it('renders user-facing names for every PriceSource', () => {
    expect(SOURCE_LABEL.BRAPI).toBe('brapi')
    expect(SOURCE_LABEL.FINNHUB).toBe('Finnhub')
    expect(SOURCE_LABEL.COINBASE).toBe('Coinbase')
    expect(SOURCE_LABEL.TESOURO).toBe('Tesouro')
    expect(SOURCE_LABEL.MANUAL).toBe('Manual')
  })
})

describe('AUTOMATED_SOURCES', () => {
  it('contains the 4 API-backed sources, excludes MANUAL', () => {
    expect(AUTOMATED_SOURCES).toContain('BRAPI')
    expect(AUTOMATED_SOURCES).toContain('FINNHUB')
    expect(AUTOMATED_SOURCES).toContain('COINBASE')
    expect(AUTOMATED_SOURCES).toContain('TESOURO')
    expect(AUTOMATED_SOURCES).not.toContain('MANUAL')
  })
})

describe('formatRelative', () => {
  const now = new Date('2026-05-24T18:00:00Z')

  it('returns "—" for null timestamp', () => {
    expect(formatRelative(null, now)).toBe('—')
  })
  it('returns "agora" for under 1 minute', () => {
    expect(formatRelative('2026-05-24T17:59:30Z', now)).toBe('agora')
  })
  it('uses minutes under 1 hour', () => {
    expect(formatRelative('2026-05-24T17:30:00Z', now)).toBe('há 30 min')
  })
  it('uses hours from 1h to 48h', () => {
    expect(formatRelative('2026-05-24T12:00:00Z', now)).toBe('há 6h')
  })
  it('uses days when older than 48h', () => {
    expect(formatRelative('2026-05-20T18:00:00Z', now)).toBe('há 4 d')
  })
})

function makeAsset(overrides: Partial<AssetOut>): AssetOut {
  return {
    id: 'a-1',
    workspace_id: 'ws-1',
    workspace_name: null,
    account_id: 'acc-1',
    account_name: 'Acc',
    financial_institution_id: 'fi-1',
    financial_institution_name: 'FI',
    asset_class: 'STOCK',
    country: 'BR',
    name: 'X',
    ticker: 'X',
    cnpj: null,
    currency: 'BRL',
    current_price: null,
    price_updated_at: null,
    price_source: null,
    price_tier: 'UNKNOWN',
    notes: null,
    external_id: null,
    external_source: null,
    is_active: true,
    created_at: '2026-01-01',
    updated_at: '2026-05-24',
    details: null,
    ...overrides,
  } as AssetOut
}

describe('aggregatePriceStats', () => {
  const now = new Date('2026-05-24T18:00:00Z')

  it('returns UNKNOWN when only MANUAL assets exist', () => {
    const stats = aggregatePriceStats(
      [makeAsset({ price_source: 'MANUAL', price_tier: 'OLD' })],
      now,
    )
    expect(stats.worstTier).toBe('UNKNOWN')
    expect(stats.totalAutomated).toBe(0)
  })

  it('picks worst tier across automated, ignoring MANUAL', () => {
    const stats = aggregatePriceStats([
      makeAsset({ id: 'a', price_source: 'BRAPI', price_tier: 'FRESH', price_updated_at: '2026-05-24T17:00:00Z' }),
      makeAsset({ id: 'b', price_source: 'FINNHUB', price_tier: 'OLD', price_updated_at: '2026-05-10T12:00:00Z' }),
      makeAsset({ id: 'c', price_source: 'MANUAL', price_tier: 'OLD', price_updated_at: '2025-01-01T00:00:00Z' }),
    ], now)
    expect(stats.worstTier).toBe('OLD')
    expect(stats.totalAutomated).toBe(2)
  })

  it('topStale lists oldest automated assets first', () => {
    const stats = aggregatePriceStats([
      makeAsset({ id: 'new', price_source: 'BRAPI', price_tier: 'FRESH', price_updated_at: '2026-05-24T17:00:00Z' }),
      makeAsset({ id: 'old', price_source: 'BRAPI', price_tier: 'OLD', price_updated_at: '2026-05-10T12:00:00Z' }),
    ], now)
    expect(stats.topStale[0].id).toBe('old')
  })
})
