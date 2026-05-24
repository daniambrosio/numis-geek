import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { RefreshCw, AlertTriangle } from 'lucide-react'

import { api, type AssetOut, type PriceSource, type RefreshSummaryOut } from '../lib/api'
import {
  TIER_COLOR, SOURCE_LABEL,
  formatRelative, aggregatePriceStats, type SourceBreakdown,
} from '../lib/price'

type RunningKind = 'all' | PriceSource | null

export default function PriceRefresh() {
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const [assets, setAssets] = useState<AssetOut[]>([])
  const [running, setRunning] = useState<RunningKind>(null)
  const [lastResult, setLastResult] = useState<RefreshSummaryOut | null>(null)
  const popRef = useRef<HTMLDivElement>(null)

  // Lazy-fetch assets the first time and after each refresh run.
  async function fetchAssets() {
    try {
      const list = await api.listAssets({ include_inactive: false })
      setAssets(list)
    } catch {
      // Silent — the popover will just show empty state.
    }
  }

  useEffect(() => {
    fetchAssets()
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
  const dotColor = TIER_COLOR[stats.worstTier]

  async function runRefresh(kind: RunningKind) {
    if (running) return
    setRunning(kind)
    setLastResult(null)
    try {
      const body = kind === 'all' || kind === null ? {} : { source: kind }
      const summary = await api.refreshPrices(body)
      setLastResult(summary)
      await fetchAssets()
    } catch (e) {
      setLastResult({
        ok: 0,
        failed: 1,
        skipped: 0,
        errors: [{ asset_id: '-', ticker: null, reason: e instanceof Error ? e.message : 'Erro' }],
        ran_at: new Date().toISOString(),
      })
    } finally {
      setRunning(null)
    }
  }

  function goToAsset(id: string) {
    setOpen(false)
    navigate(`/assets/${id}`)
  }

  return (
    <div className="relative" ref={popRef}>
      <button
        onClick={() => setOpen(o => !o)}
        title="Atualização de preços"
        className="h-8 px-2.5 inline-flex items-center gap-1.5 rounded-lg text-[11px] text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
      >
        <RefreshCw
          className={`w-3.5 h-3.5 ${running ? 'animate-spin' : ''}`}
          strokeWidth={1.6}
        />
        <span>{running ? 'Atualizando…' : stats.oldestAge}</span>
        <span
          className="w-2 h-2 rounded-full"
          style={{ background: dotColor }}
          aria-label={`Status: ${stats.worstTier.toLowerCase()}`}
        />
      </button>

      {open && (
        <div className="menu-pop absolute right-0 mt-2 w-80 rounded-xl bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 shadow-2xl shadow-black/30 p-3 z-50">
          {/* Header */}
          <div className="px-1 pb-2 border-b border-gray-100 dark:border-gray-800">
            <div className="text-[12px] font-semibold text-gray-900 dark:text-gray-100">
              Preços
            </div>
            <div className="text-[11px] text-gray-500 dark:text-gray-400">
              Mais antigo: {stats.oldestAge} · {stats.totalAutomated} ativos automatizados
            </div>
          </div>

          {/* Update all */}
          <button
            onClick={() => runRefresh('all')}
            disabled={running !== null}
            className="mt-2 w-full h-8 inline-flex items-center justify-center gap-1.5 rounded-lg bg-indigo-500 hover:bg-indigo-400 disabled:opacity-50 text-white text-[12px] font-medium transition-colors"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${running === 'all' ? 'animate-spin' : ''}`} />
            {running === 'all' ? 'Atualizando todos…' : 'Atualizar agora'}
          </button>

          {/* Per-source */}
          <div className="mt-3 px-1">
            <div className="text-[10px] uppercase tracking-wider font-semibold text-gray-500 dark:text-gray-400 mb-1">
              Fontes
            </div>
            <div className="space-y-0.5">
              {stats.perSource.length === 0 && (
                <div className="text-[11px] text-gray-500 dark:text-gray-500 px-1 py-1">
                  Nenhum ativo automatizado.
                </div>
              )}
              {stats.perSource.map(b => (
                <SourceRow
                  key={b.source}
                  breakdown={b}
                  running={running === b.source}
                  disabled={running !== null}
                  onClick={() => runRefresh(b.source)}
                />
              ))}
            </div>
          </div>

          {/* Result panel */}
          {lastResult && (
            <div
              className={`mt-3 mx-1 rounded-lg border px-2 py-2 text-[11px] ${
                lastResult.failed > 0
                  ? 'bg-amber-50 dark:bg-amber-900/20 border-amber-200 dark:border-amber-900 text-amber-700 dark:text-amber-300'
                  : 'bg-emerald-50 dark:bg-emerald-900/20 border-emerald-200 dark:border-emerald-900 text-emerald-700 dark:text-emerald-300'
              }`}
            >
              <div>
                {lastResult.ok} OK · {lastResult.skipped} ignorados · {lastResult.failed} falhas
              </div>
              {lastResult.errors.length > 0 && (
                <details className="mt-1">
                  <summary className="cursor-pointer inline-flex items-center gap-1">
                    <AlertTriangle className="w-3 h-3" /> Ver falhas
                  </summary>
                  <ul className="mt-1 ml-3 list-disc">
                    {lastResult.errors.slice(0, 3).map(e => (
                      <li key={e.asset_id}>
                        {e.ticker ?? e.asset_id}: {e.reason}
                      </li>
                    ))}
                    {lastResult.errors.length > 3 && (
                      <li className="opacity-70">+ {lastResult.errors.length - 3} mais</li>
                    )}
                  </ul>
                </details>
              )}
            </div>
          )}

          {/* Top stale */}
          {stats.topStale.length > 0 && (
            <div className="mt-3 px-1">
              <div className="text-[10px] uppercase tracking-wider font-semibold text-gray-500 dark:text-gray-400 mb-1">
                Top desatualizados
              </div>
              <div className="space-y-0.5">
                {stats.topStale.map(a => (
                  <button
                    key={a.id}
                    onClick={() => goToAsset(a.id)}
                    className="w-full text-left flex items-center gap-2 px-2 py-1 rounded-md hover:bg-gray-100 dark:hover:bg-gray-800/50 text-[11px] transition-colors"
                  >
                    <span
                      className="w-1.5 h-1.5 rounded-full shrink-0"
                      style={{ background: TIER_COLOR[a.price_tier] }}
                    />
                    <span className="flex-1 truncate text-gray-700 dark:text-gray-200">
                      {a.ticker ?? a.name}
                    </span>
                    <span className="text-gray-500 dark:text-gray-500 shrink-0">
                      {formatRelative(a.price_updated_at)}
                    </span>
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Footer */}
          <div className="mt-3 pt-2 px-1 border-t border-gray-100 dark:border-gray-800 text-[10px] text-gray-500 dark:text-gray-500 leading-relaxed">
            Atualizações automáticas diárias às 18h. Ativos manuais precisam ser editados no detalhe.
          </div>
        </div>
      )}
    </div>
  )
}

function SourceRow({
  breakdown,
  running,
  disabled,
  onClick,
}: {
  breakdown: SourceBreakdown
  running: boolean
  disabled: boolean
  onClick: () => void
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className="w-full flex items-center gap-2 px-2 py-1 rounded-md hover:bg-gray-100 dark:hover:bg-gray-800/50 disabled:opacity-50 disabled:hover:bg-transparent text-[11px] transition-colors"
    >
      <span
        className="w-1.5 h-1.5 rounded-full shrink-0"
        style={{ background: TIER_COLOR[breakdown.worstTier] }}
      />
      <span className="flex-1 text-left text-gray-700 dark:text-gray-200">
        {SOURCE_LABEL[breakdown.source]}
      </span>
      {running ? (
        <RefreshCw className="w-3 h-3 animate-spin text-indigo-500" />
      ) : (
        <span className="text-gray-500 dark:text-gray-500">{breakdown.count}</span>
      )}
    </button>
  )
}

