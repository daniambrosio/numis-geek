/* Spec 44 — PriceRefresh popover (topbar refresh widget).
 *
 * Mirrors prototypes/index.html ~1856 (PriceRefresh function) and adds the
 * PTAX block (sub-section that surfaces FX freshness — critical for the
 * dual-currency views from Spec 41).
 *
 * Visual rules (follow-prototype-strictly):
 * - Source dots are gray-400 by default. Only colored during/after refresh.
 *   (Current real-app behavior — color by worst tier — was noisy.)
 * - Header has the "Atualizar agora" button inline top-right (h-7), not below.
 * - Manual source rendered with dashed top border, NOT clickable.
 * - "Mais desatualizados" carries (N) count in the title and filters
 *   to stale-only.
 *
 * Capability extension (consciously diverges from proto): per-source rows
 * remain clickable — clicking a source triggers a refresh limited to that
 * source. Useful when one provider is flaky. Visual stays clean.
 */
import { useEffect, useRef, useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { RefreshCw, AlertTriangle, Check } from 'lucide-react'

import {
  api, type AssetOut, type PriceSource, type PTAXStatusOut,
  type RefreshSummaryOut,
} from '../lib/api'
import {
  AUTOMATED_SOURCES, TIER_COLOR,
  aggregatePriceStats, formatRelative, ptaxTier, worstOfTiers,
} from '../lib/price'

type RunningKind = 'all' | PriceSource | null

const SOURCE_DISPLAY: Record<PriceSource, string> = {
  BRAPI: 'B3 / brapi',
  FINNHUB: 'Finnhub',
  COINBASE: 'Coinbase',
  TESOURO: 'Tesouro Direto',
  MANUAL: 'Manual',
}

function fmtDateBR(iso: string | null): string {
  if (!iso) return '—'
  // iso is YYYY-MM-DD (date only). Avoid TZ shift.
  const [y, m, d] = iso.split('-')
  return `${d}/${m}/${y}`
}

function ptaxAgeRelative(lastDateIso: string | null, now: Date = new Date()): string {
  if (!lastDateIso) return '—'
  return formatRelative(lastDateIso + 'T23:59:59', now)
}

export default function PriceRefresh() {
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const [assets, setAssets] = useState<AssetOut[]>([])
  const [running, setRunning] = useState<RunningKind>(null)
  const [lastResult, setLastResult] = useState<RefreshSummaryOut | null>(null)
  const [lastSource, setLastSource] = useState<RunningKind>(null)
  const [ptax, setPtax] = useState<PTAXStatusOut | null>(null)
  const [ptaxSyncing, setPtaxSyncing] = useState(false)
  const popRef = useRef<HTMLDivElement>(null)

  async function fetchAssets() {
    try {
      const list = await api.listAssets({ include_inactive: false })
      setAssets(list)
    } catch { /* silent */ }
  }

  async function fetchPtax() {
    try {
      const s = await api.ptaxStatusWorkspace()
      setPtax(s)
    } catch { /* silent — PTAX block still shows "—" */ }
  }

  useEffect(() => {
    fetchAssets()
    fetchPtax()
  }, [])

  // Click-outside + ESC
  useEffect(() => {
    if (!open) return
    function onDown(e: MouseEvent) {
      const t = e.target as Node
      if (popRef.current && !popRef.current.contains(t)) setOpen(false)
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  const stats = aggregatePriceStats(assets)
  // Worst-of(asset oldest tier, PTAX age tier) drives the pill dot color.
  const ptaxAgeT = ptaxTier(ptax?.last_date ?? null)
  const pillTier = worstOfTiers(stats.worstTier, ptaxAgeT)
  const dotColor = TIER_COLOR[pillTier]
  // Pill age: worst-of textual rendering — show whichever is older.
  // (When PTAX is older than the oldest asset price, show PTAX age.)
  const pillAge = (() => {
    const assetMs = stats.oldestAge !== '—' ? parseAge(stats.oldestAge) : null
    const ptaxMs = ptax?.last_date ? Date.now() - new Date(ptax.last_date + 'T23:59:59').getTime() : null
    if (assetMs == null && ptaxMs == null) return '—'
    if (assetMs == null) return ptaxAgeRelative(ptax!.last_date)
    if (ptaxMs == null) return stats.oldestAge
    return ptaxMs > assetMs ? ptaxAgeRelative(ptax!.last_date) : stats.oldestAge
  })()

  // Source aggregations (re-derived here to include MANUAL count which
  // aggregatePriceStats intentionally hides).
  const manualCount = assets.filter(a => a.price_source === 'MANUAL').length
  const countBy = (src: PriceSource) =>
    assets.filter(a => a.price_source === src).length

  // Stale-only list (proto-style — exclude FRESH).
  const staleAssets = [...assets]
    .filter(a => a.price_source && AUTOMATED_SOURCES.includes(a.price_source))
    .filter(a => a.price_tier === 'STALE' || a.price_tier === 'OLD')
    .sort((a, b) => {
      const at = a.price_updated_at ? new Date(a.price_updated_at).getTime() : 0
      const bt = b.price_updated_at ? new Date(b.price_updated_at).getTime() : 0
      return at - bt
    })

  async function runRefresh(kind: RunningKind) {
    if (running) return
    setRunning(kind)
    setLastResult(null)
    try {
      const body = kind === 'all' || kind === null ? {} : { source: kind as PriceSource }
      const summary = await api.refreshPrices(body)
      setLastResult(summary)
      setLastSource(kind)
      await fetchAssets()
    } catch (e) {
      setLastResult({
        ok: 0,
        failed: 1,
        skipped: 0,
        errors: [{ asset_id: '-', ticker: null, reason: e instanceof Error ? e.message : 'Erro' }],
        ran_at: new Date().toISOString(),
      })
      setLastSource(kind)
    } finally {
      setRunning(null)
    }
  }

  async function syncPtax() {
    if (ptaxSyncing) return
    setPtaxSyncing(true)
    try {
      await api.syncPtaxWorkspace('incremental')
      await fetchPtax()
    } catch { /* keep silent; the pill keeps the old age */ }
    finally { setPtaxSyncing(false) }
  }

  function goToAsset(id: string) {
    setOpen(false)
    navigate(`/assets/${id}`)
  }

  // Determine per-source visual state:
  // - running this source OR running 'all' → indigo-pulse
  // - lastResult covers this source (lastSource === src or 'all') and lastResult.failed === 0 → emerald
  // - same but failed > 0 → amber
  // - else → gray
  function dotClsForSource(src: PriceSource): string {
    if (running === src || running === 'all') return 'bg-indigo-500 animate-pulse'
    if (lastResult && (lastSource === src || lastSource === 'all')) {
      return lastResult.failed > 0 ? 'bg-amber-500' : 'bg-emerald-500'
    }
    return 'bg-gray-400'
  }

  function counterForSource(src: PriceSource): string | null {
    if (!lastResult || (lastSource !== src && lastSource !== 'all')) return null
    const n = countBy(src)
    if (n === 0) return null
    // Per-source counter is best-effort given the global summary shape.
    // When refreshing a single source, ok/failed apply directly.
    // When 'all', distribute proportionally is misleading — fall back to total.
    if (lastSource === src) {
      return `${lastResult.ok}/${lastResult.ok + lastResult.failed}`
    }
    return null
  }

  return (
    <div className="relative" ref={popRef}>
      <button
        onClick={() => setOpen(o => !o)}
        title="Preços e PTAX"
        className="h-8 px-2.5 inline-flex items-center gap-1.5 rounded-lg text-[11px] text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
      >
        <RefreshCw
          className={`w-3.5 h-3.5 ${running || ptaxSyncing ? 'animate-spin' : ''}`}
          strokeWidth={1.6}
        />
        <span className="tnum">{running || ptaxSyncing ? 'Atualizando…' : pillAge}</span>
        <span
          className="w-2 h-2 rounded-full"
          style={{ background: dotColor }}
          aria-label={`Status: ${pillTier.toLowerCase()}`}
          data-testid="price-refresh-dot"
        />
      </button>

      {open && (
        <div className="menu-pop absolute right-0 top-10 z-50 w-[360px] rounded-xl bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 shadow-2xl shadow-black/30 overflow-hidden">
          {/* Header — Preços dos ativos */}
          <div className="px-4 pt-3.5 pb-3 border-b border-gray-200 dark:border-gray-800">
            <div className="flex items-center justify-between gap-3">
              <div className="min-w-0">
                <div className="text-[13px] font-semibold text-gray-900 dark:text-gray-100">
                  Preços dos ativos
                </div>
                <div className="text-[11px] text-gray-500 dark:text-gray-400 mt-0.5">
                  Mais antigo:{' '}
                  <span
                    className="tnum font-medium"
                    style={{ color: TIER_COLOR[stats.worstTier] }}
                  >
                    {stats.oldestAge}
                  </span>
                  {' · '}
                  <span className="tnum">{stats.totalAutomated} ativos</span>
                </div>
              </div>
              <button
                onClick={() => runRefresh('all')}
                disabled={running !== null}
                className={`inline-flex items-center gap-1.5 h-7 px-2.5 rounded-md text-[11px] font-medium transition-colors shrink-0 ${
                  running !== null
                    ? 'bg-gray-200 dark:bg-gray-800 text-gray-500 cursor-not-allowed'
                    : 'bg-indigo-500 hover:bg-indigo-400 text-white'
                }`}
              >
                <RefreshCw className={`w-3 h-3 ${running === 'all' ? 'animate-spin' : ''}`} />
                {running === 'all' ? 'Atualizando…' : 'Atualizar agora'}
              </button>
            </div>
          </div>

          {/* Fontes */}
          <div className="px-4 py-3 space-y-1.5 border-b border-gray-200 dark:border-gray-800">
            <div className="text-[10px] uppercase tracking-wider font-medium text-gray-500 mb-1">
              Fontes
            </div>
            {AUTOMATED_SOURCES.map(src => {
              const n = countBy(src)
              if (n === 0) return null
              const counter = counterForSource(src)
              return (
                <button
                  key={src}
                  onClick={() => runRefresh(src)}
                  disabled={running !== null}
                  className="w-full flex items-center gap-2 text-[11px] py-1 -mx-1 px-1 rounded hover:bg-gray-100 dark:hover:bg-gray-800/50 disabled:opacity-60 disabled:hover:bg-transparent transition-colors"
                  data-testid={`source-row-${src}`}
                >
                  <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${dotClsForSource(src)}`} />
                  <span className="text-gray-700 dark:text-gray-300 font-medium">
                    {SOURCE_DISPLAY[src]}
                  </span>
                  <span className="text-gray-500">
                    · {n} {n === 1 ? 'ativo' : 'ativos'}
                  </span>
                  <div className="flex-1" />
                  {counter && (
                    <span
                      className={`text-[10px] ${
                        lastResult && lastResult.failed > 0
                          ? 'text-amber-500 dark:text-amber-400'
                          : 'text-emerald-500 dark:text-emerald-400'
                      }`}
                    >
                      {counter}
                    </span>
                  )}
                </button>
              )
            })}
            {manualCount > 0 && (
              <div className="flex items-center gap-2 text-[11px] pt-1.5 mt-1 border-t border-dashed border-gray-200 dark:border-gray-800">
                <span className="w-1.5 h-1.5 rounded-full bg-gray-400" />
                <span className="text-gray-500">
                  Manual · {manualCount} {manualCount === 1 ? 'ativo' : 'ativos'} (atualizar no detalhe)
                </span>
              </div>
            )}
          </div>

          {/* Result panel */}
          {lastResult && !running && (
            <div className="px-4 py-3 border-b border-gray-200 dark:border-gray-800 bg-emerald-50/50 dark:bg-emerald-500/5">
              <div className="flex items-center gap-2 text-[12px]">
                {lastResult.failed === 0 ? (
                  <Check className="w-3.5 h-3.5 text-emerald-500 dark:text-emerald-400" />
                ) : (
                  <AlertTriangle className="w-3.5 h-3.5 text-amber-500 dark:text-amber-400" />
                )}
                <span
                  className={`font-medium ${
                    lastResult.failed === 0
                      ? 'text-emerald-700 dark:text-emerald-300'
                      : 'text-amber-700 dark:text-amber-300'
                  }`}
                >
                  {lastResult.ok} de {lastResult.ok + lastResult.failed} atualizados
                </span>
              </div>
              {lastResult.errors.slice(0, 3).map((e, i) => (
                <div
                  key={i}
                  className="mt-1.5 text-[11px] flex items-center gap-2 text-amber-700 dark:text-amber-400"
                >
                  <AlertTriangle className="w-3 h-3 shrink-0" />
                  <span className="font-mono">{e.ticker ?? e.asset_id}</span>
                  <span className="text-gray-500">· {e.reason}</span>
                </div>
              ))}
              {lastResult.errors.length > 3 && (
                <div className="mt-1 text-[10px] text-gray-500">
                  + {lastResult.errors.length - 3} mais
                </div>
              )}
            </div>
          )}

          {/* Mais desatualizados */}
          {staleAssets.length > 0 && !running && (
            <div className="px-4 py-3 max-h-[200px] overflow-y-auto border-b border-gray-200 dark:border-gray-800">
              <div
                className="text-[10px] uppercase tracking-wider font-medium text-gray-500 mb-1.5"
                data-testid="stale-title"
              >
                Mais desatualizados ({staleAssets.length})
              </div>
              {staleAssets.slice(0, 5).map(a => (
                <button
                  key={a.id}
                  onClick={() => goToAsset(a.id)}
                  className="w-full flex items-center gap-2 py-1.5 -mx-1 px-1 rounded-md text-[11px] hover:bg-gray-100 dark:hover:bg-gray-800/50 transition-colors text-left"
                >
                  <span
                    className={`w-1 h-4 rounded-full shrink-0 ${
                      a.price_tier === 'OLD' ? 'bg-red-500' : 'bg-amber-500'
                    }`}
                  />
                  <span className="font-mono font-medium text-gray-800 dark:text-gray-200">
                    {a.ticker ?? a.name.slice(0, 16)}
                  </span>
                  <div className="flex-1" />
                  <span className="text-gray-500 tnum">
                    {formatRelative(a.price_updated_at)}
                  </span>
                </button>
              ))}
              {staleAssets.length > 5 && (
                <Link
                  to="/assets"
                  onClick={() => setOpen(false)}
                  className="block text-[11px] text-indigo-500 dark:text-indigo-400 hover:underline mt-2"
                >
                  Ver todos {staleAssets.length} desatualizados em Ativos →
                </Link>
              )}
            </div>
          )}

          {/* PTAX (Spec 44) */}
          <div className="px-4 py-3 border-b border-gray-200 dark:border-gray-800">
            <div className="flex items-center justify-between gap-3">
              <div className="min-w-0">
                <div className="text-[13px] font-semibold text-gray-900 dark:text-gray-100">
                  PTAX
                </div>
                <div className="text-[11px] text-gray-500 dark:text-gray-400 mt-0.5">
                  {ptax ? (
                    <>
                      Último:{' '}
                      <span className="tnum">{fmtDateBR(ptax.last_date)}</span>
                      {' · '}
                      <span
                        className="tnum font-medium"
                        style={{ color: TIER_COLOR[ptaxAgeT] }}
                        data-testid="ptax-age"
                      >
                        {ptaxAgeRelative(ptax.last_date)}
                      </span>
                    </>
                  ) : (
                    <span className="text-gray-400">—</span>
                  )}
                </div>
                {ptax && (
                  <div className="text-[10px] text-gray-500 dark:text-gray-600 mt-0.5 tnum">
                    {ptax.total_rows} cotações armazenadas
                  </div>
                )}
              </div>
              <button
                onClick={syncPtax}
                disabled={ptaxSyncing}
                className={`inline-flex items-center gap-1.5 h-7 px-2.5 rounded-md text-[11px] font-medium transition-colors shrink-0 ${
                  ptaxSyncing
                    ? 'bg-gray-200 dark:bg-gray-800 text-gray-500 cursor-not-allowed'
                    : 'bg-indigo-500 hover:bg-indigo-400 text-white'
                }`}
                data-testid="ptax-sync-button"
              >
                <RefreshCw className={`w-3 h-3 ${ptaxSyncing ? 'animate-spin' : ''}`} />
                {ptaxSyncing ? 'Sincronizando…' : 'Sincronizar'}
              </button>
            </div>
          </div>

          {/* Footer */}
          <div className="px-4 py-2 text-[10px] text-gray-500 dark:text-gray-500 leading-relaxed">
            Atualizações automáticas diárias às 18h (preços) e 20h (PTAX). Ativos manuais
            (imóveis, veículo) precisam ser editados no detalhe.
          </div>
        </div>
      )}
    </div>
  )
}

/** Best-effort parser of "há Xm/h/d/a" back to milliseconds. Used only
 *  to decide which age to show in the topbar pill (asset vs PTAX). */
function parseAge(rel: string): number | null {
  if (rel === 'agora') return 0
  const m = rel.match(/^há (\d+)\s*(min|h|d|m|a)$/)
  if (!m) return null
  const n = parseInt(m[1], 10)
  switch (m[2]) {
    case 'min': return n * 60_000
    case 'h':   return n * 3_600_000
    case 'd':   return n * 86_400_000
    case 'm':   return n * 30 * 86_400_000
    case 'a':   return n * 365 * 86_400_000
  }
  return null
}
