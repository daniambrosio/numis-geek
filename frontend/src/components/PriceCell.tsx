/* Spec 26 — "Atualizado" cell for the Assets table.
 *
 * Renders the freshness dot + relative age. For automated sources, also
 * renders a per-row refresh button that calls POST /assets/{id}/refresh-price
 * and reports the updated asset back to the parent so the row can re-render
 * without refetching the whole list. */
import { useState } from 'react'
import { RefreshCw } from 'lucide-react'

import { api, type AssetOut } from '../lib/api'
import {
  TIER_COLOR, SOURCE_LABEL, AUTOMATED_SOURCES, formatRelative,
} from '../lib/price'

interface Props {
  asset: AssetOut
  onUpdated?: (updated: AssetOut) => void
  /** Override now() for tests. */
  now?: Date
}

function fmtTooltip(asset: AssetOut): string {
  const source = asset.price_source
    ? SOURCE_LABEL[asset.price_source]
    : 'sem fonte'
  if (!asset.price_updated_at) {
    return `${source} · nunca atualizado`
  }
  // Local time, no seconds
  const iso = new Date(asset.price_updated_at).toLocaleString('pt-BR', {
    day: '2-digit', month: '2-digit', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
  return `${source} · ${iso}`
}

export default function PriceCell({ asset, onUpdated, now }: Props) {
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const automated =
    asset.price_source !== null &&
    asset.price_source !== undefined &&
    AUTOMATED_SOURCES.includes(asset.price_source)
  const tier = asset.price_tier
  const age = formatRelative(asset.price_updated_at, now)

  async function handleRefresh(e: React.MouseEvent) {
    e.stopPropagation()
    e.preventDefault()
    if (busy) return
    setBusy(true)
    setErr(null)
    try {
      const r = await api.refreshAssetPrice(asset.id)
      if (r.status !== 'ok') {
        setErr(r.error ?? r.status)
        return
      }
      // Refetch this single asset so we get fresh price_source / price_tier /
      // price_updated_at without paying for the full list.
      const fresh = await api.getAsset(asset.id)
      onUpdated?.(fresh)
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : 'Erro')
    } finally {
      setBusy(false)
      if (err) window.setTimeout(() => setErr(null), 3000)
    }
  }

  return (
    <div className="inline-flex items-center gap-1.5" title={err ?? fmtTooltip(asset)}>
      <span
        className="w-1.5 h-1.5 rounded-full shrink-0"
        style={{ background: TIER_COLOR[tier] }}
        aria-label={`tier ${tier.toLowerCase()}`}
      />
      <span className="text-[11px] text-gray-500 dark:text-gray-400 tnum">
        {age}
      </span>
      {automated && (
        <button
          type="button"
          onClick={handleRefresh}
          disabled={busy}
          title={`Atualizar via ${asset.price_source ? SOURCE_LABEL[asset.price_source] : ''}`}
          aria-label={`Atualizar preço de ${asset.ticker ?? asset.name}`}
          className="ml-0.5 w-5 h-5 inline-flex items-center justify-center rounded hover:bg-gray-200 dark:hover:bg-gray-800 text-gray-500 hover:text-gray-700 dark:hover:text-gray-300 disabled:opacity-50 transition-colors"
        >
          <RefreshCw
            className={`w-3 h-3 ${busy ? 'animate-spin' : ''}`}
            strokeWidth={1.8}
          />
        </button>
      )}
    </div>
  )
}
