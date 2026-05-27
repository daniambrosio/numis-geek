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

const TIER_RANK_FULL: Record<PriceTier, number> = {
  FRESH: 0, STALE: 1, OLD: 2, UNKNOWN: 3,
}

/** PTAX freshness (Spec 44). BCB cron runs daily 20h SP, so anything
 *  ≤24h is FRESH, 1–3 dias STALE, > 3 dias OLD. */
export function ptaxTier(lastDateIso: string | null, now: Date = new Date()): PriceTier {
  if (!lastDateIso) return 'UNKNOWN'
  // lastDateIso is a YYYY-MM-DD (BR business day). Use end-of-day SP as baseline.
  const ts = new Date(lastDateIso + 'T23:59:59').getTime()
  const diffH = (now.getTime() - ts) / 3_600_000
  if (diffH <= 24) return 'FRESH'
  if (diffH <= 72) return 'STALE'
  return 'OLD'
}

/** Take the worst of two tiers — UNKNOWN is treated as "no signal" and
 *  doesn't downgrade a real tier (Spec 44). */
export function worstOfTiers(a: PriceTier, b: PriceTier): PriceTier {
  if (a === 'UNKNOWN') return b
  if (b === 'UNKNOWN') return a
  return TIER_RANK_FULL[a] >= TIER_RANK_FULL[b] ? a : b
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
