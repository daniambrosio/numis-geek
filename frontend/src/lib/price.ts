import type { AssetOut, PriceSource, PriceTier } from './api'

export const TIER_COLOR: Record<PriceTier, string> = {
  FRESH: '#22c55e',
  STALE: '#f59e0b',
  OLD: '#ef4444',
  UNKNOWN: '#94a3b8',
}

export const SOURCE_LABEL: Record<PriceSource, string> = {
  BRAPI: 'brapi',
  FINNHUB: 'Finnhub',
  COINBASE: 'Coinbase',
  TESOURO: 'Tesouro',
  MANUAL: 'Manual',
}

export const AUTOMATED_SOURCES: readonly PriceSource[] = [
  'BRAPI', 'FINNHUB', 'COINBASE', 'TESOURO',
]

const TIER_RANK: Record<PriceTier, number> = {
  FRESH: 0, STALE: 1, OLD: 2, UNKNOWN: 3,
}

/** "há 9h" / "há 3 d" / "agora" / "—" (when iso null). */
export function formatRelative(iso: string | null, now: Date = new Date()): string {
  if (!iso) return '—'
  const ts = new Date(iso).getTime()
  const diffMs = now.getTime() - ts
  if (diffMs < 0) return 'agora'
  const minutes = Math.floor(diffMs / 60_000)
  if (minutes < 1) return 'agora'
  if (minutes < 60) return `há ${minutes} min`
  const hours = Math.floor(minutes / 60)
  if (hours < 48) return `há ${hours}h`
  const days = Math.floor(hours / 24)
  if (days < 30) return `há ${days} d`
  const months = Math.floor(days / 30)
  if (months < 12) return `há ${months} m`
  const years = Math.floor(days / 365)
  return `há ${years} a`
}

export interface SourceBreakdown {
  source: PriceSource
  count: number
  worstTier: PriceTier
}

export interface PriceStats {
  worstTier: PriceTier
  oldestAge: string
  totalAutomated: number
  perSource: SourceBreakdown[]
  topStale: AssetOut[]
}

/** Worst tier across automated-source assets (MANUAL ignored). */
export function aggregatePriceStats(assets: AssetOut[], now: Date = new Date()): PriceStats {
  const automated = assets.filter(a => a.price_source && AUTOMATED_SOURCES.includes(a.price_source))

  let worst: PriceTier = 'UNKNOWN'
  let oldestTs: number | null = null
  for (const a of automated) {
    if (TIER_RANK[a.price_tier] > TIER_RANK[worst] && a.price_tier !== 'UNKNOWN') {
      worst = a.price_tier
    } else if (worst === 'UNKNOWN' && a.price_tier !== 'UNKNOWN') {
      worst = a.price_tier
    }
    if (a.price_updated_at) {
      const ts = new Date(a.price_updated_at).getTime()
      if (oldestTs === null || ts < oldestTs) oldestTs = ts
    }
  }

  const perSource: SourceBreakdown[] = AUTOMATED_SOURCES.map(src => {
    const subset = automated.filter(a => a.price_source === src)
    let wt: PriceTier = 'UNKNOWN'
    for (const a of subset) {
      if (TIER_RANK[a.price_tier] > TIER_RANK[wt] && a.price_tier !== 'UNKNOWN') {
        wt = a.price_tier
      } else if (wt === 'UNKNOWN' && a.price_tier !== 'UNKNOWN') {
        wt = a.price_tier
      }
    }
    return { source: src, count: subset.length, worstTier: wt }
  }).filter(b => b.count > 0)

  const topStale = [...automated]
    .filter(a => a.price_updated_at !== null || a.price_tier !== 'UNKNOWN')
    .sort((a, b) => {
      const at = a.price_updated_at ? new Date(a.price_updated_at).getTime() : 0
      const bt = b.price_updated_at ? new Date(b.price_updated_at).getTime() : 0
      return at - bt   // oldest first
    })
    .slice(0, 5)

  return {
    worstTier: automated.length === 0 ? 'UNKNOWN' : worst,
    oldestAge: oldestTs ? formatRelative(new Date(oldestTs).toISOString(), now) : '—',
    totalAutomated: automated.length,
    perSource,
    topStale,
  }
}
