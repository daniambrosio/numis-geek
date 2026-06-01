/* Spec 48 — Bulk extract review modal.
 *
 * Opens after BulkUploadZone completes extraction. Shows 3 sections:
 *   - Casadas (will resolve)
 *   - Linhas órfãs (ticker not in workspace, ignored)
 *   - Pendências não cobertas no extrato (info only)
 *
 * Optional FI dropdown — picks the FI to scope matching to. V1: this is
 * passed as metadata to confirmExtraction; the backend filters matches.
 */
import { useEffect, useMemo, useState } from 'react'
import { Sparkles, X } from 'lucide-react'

import {
  api,
  type BulkExtractJobOut,
  type FinancialInstitutionOut,
  type SnapshotPendencyOut,
} from '../lib/api'

interface Props {
  job: BulkExtractJobOut
  pendencies: SnapshotPendencyOut[]
  onApplied: (appliedCount: number) => void
  onClose: () => void
}

type ExtractedPosition = {
  ticker_raw?: string
  ticker_normalized?: string | null
  unit_price?: number
  quantity?: number
}

function fmtBRL(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return '—'
  return n.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })
}

function tickerOf(pos: ExtractedPosition): string | null {
  return pos.ticker_normalized || pos.ticker_raw || null
}

export default function BulkExtractReviewModal({
  job, pendencies, onApplied, onClose,
}: Props) {
  const [fis, setFis] = useState<FinancialInstitutionOut[]>([])
  const [fiShortName, setFiShortName] = useState<string>('')
  const [applying, setApplying] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // Spec 49 hotfix — manual orphan→pendency mapping. key = ticker_raw, value = pendency_id.
  const [manualMappings, setManualMappings] = useState<Record<string, string>>({})
  // Spec 49 hotfix — manual price override per ticker_raw (for extracts where
  // unit_price was null — previdência statements, custom funds, etc).
  const [manualPrices, setManualPrices] = useState<Record<string, string>>({})

  useEffect(() => {
    api.listFinancialInstitutions().then(setFis).catch(() => { /* silent */ })
  }, [])

  const positions: ExtractedPosition[] = useMemo(() => {
    const j = job.extracted_json as { positions?: ExtractedPosition[] } | null
    return j?.positions ?? []
  }, [job])

  // Client-side preview: classify each position against open pendencies by ticker.
  // The backend does the authoritative version on confirm; this is just so the
  // user sees what will happen.
  const openPendencies = useMemo(
    () => pendencies.filter(p => !p.resolved_at),
    [pendencies],
  )
  const pendencyByTicker = useMemo(() => {
    const m = new Map<string, SnapshotPendencyOut>()
    for (const p of openPendencies) {
      if (p.asset_ticker) m.set(p.asset_ticker, p)
    }
    return m
  }, [openPendencies])

  const preview = useMemo(() => {
    const matched: Array<{ ticker: string; pendency: SnapshotPendencyOut; price: number; manual: boolean }> = []
    const orphan: Array<{ ticker: string; price: number | null }> = []
    const matchedAssetIds = new Set<string>()
    const pendencyById = new Map(openPendencies.map(p => [p.id, p]))
    for (const pos of positions) {
      const t = tickerOf(pos)
      if (!t) continue
      const price = typeof pos.unit_price === 'number' ? pos.unit_price : null
      // Manual override always wins (Spec 49 hotfix).
      const manualPenId = manualMappings[pos.ticker_raw || ''] ?? manualMappings[t]
      if (manualPenId) {
        const forced = pendencyById.get(manualPenId)
        if (forced) {
          matched.push({ ticker: t, pendency: forced, price: price ?? NaN, manual: true })
          matchedAssetIds.add(forced.asset_id)
          continue
        }
      }
      const p = pendencyByTicker.get(t)
      if (p && (fiShortName === '' || p.asset_institution_short_name === fiShortName)) {
        matched.push({ ticker: t, pendency: p, price: price ?? NaN, manual: false })
        matchedAssetIds.add(p.asset_id)
      } else if (p) {
        // Pendency exists but is from another FI — skip (backend will too).
      } else {
        orphan.push({ ticker: t, price })
      }
    }
    const notCovered = openPendencies.filter(p => {
      if (matchedAssetIds.has(p.asset_id)) return false
      if (fiShortName && p.asset_institution_short_name !== fiShortName) return false
      return true
    })
    return { matched, orphan, notCovered }
  }, [positions, pendencyByTicker, openPendencies, fiShortName, manualMappings])

  async function handleApply() {
    setApplying(true); setError(null)
    try {
      // Parse manual price overrides ("1.234,56" → 1234.56).
      const priceMap: Record<string, number> = {}
      for (const [k, v] of Object.entries(manualPrices)) {
        const normalized = v.replace(/\./g, '').replace(',', '.').trim()
        const n = Number(normalized)
        if (Number.isFinite(n) && n > 0) priceMap[k] = n
      }
      const result = await api.confirmExtraction(job.id, {
        institution_short_name: fiShortName || null,
        manual_mappings: Object.keys(manualMappings).length ? manualMappings : null,
        manual_prices: Object.keys(priceMap).length ? priceMap : null,
      })
      // Spec 49 hotfix — when matches were expected but none applied
      // (e.g. unit_price null + no manual price), surface result.errors
      // in the modal so the user knows what to fix instead of the modal
      // closing silently with zero effect.
      if (result.applied_count === 0 && preview.matched.length > 0) {
        const detail = (result.errors ?? []).join(' · ') || 'Nenhuma pendência foi resolvida.'
        setError(detail)
        setApplying(false)
        return
      }
      onApplied(result.applied_count)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Erro')
      setApplying(false)
    }
  }

  async function handleCancel() {
    try { await api.rejectExtraction(job.id, 'descartado pelo usuário') }
    catch { /* best-effort */ }
    onClose()
  }

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/60 p-4">
      <div className="w-full max-w-3xl bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-700 shadow-2xl flex flex-col max-h-[90vh]">
        <div className="px-5 py-3 border-b border-gray-200 dark:border-gray-800 flex items-center justify-between">
          <div>
            <div className="text-sm font-semibold text-gray-900 dark:text-white">
              Revisar extração
            </div>
            <div className="text-[11px] text-gray-500 flex items-center gap-1">
              <Sparkles className="w-3 h-3 text-indigo-500" />
              {positions.length} linha{positions.length === 1 ? '' : 's'} extraídas
            </div>
          </div>
          <button
            onClick={handleCancel}
            className="w-7 h-7 inline-flex items-center justify-center rounded-md text-gray-400 hover:text-gray-700 dark:hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800"
            aria-label="Fechar"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="p-5 overflow-y-auto flex-1 space-y-4">
          <div className="flex items-center gap-3 flex-wrap">
            <label className="text-[12px] text-gray-600 dark:text-gray-300">
              Esse extrato é da:
            </label>
            <select
              value={fiShortName}
              onChange={e => setFiShortName(e.target.value)}
              className="h-8 px-2 text-[12px] rounded-md border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800"
              data-testid="bulk-review-fi-select"
            >
              <option value="">(qualquer FI)</option>
              {fis.filter(f => f.is_active).map(f => (
                <option key={f.id} value={f.short_name}>{f.short_name}</option>
              ))}
            </select>
            <span className="text-[11px] text-gray-500">
              Filtra o matching: só pendências dessa FI serão resolvidas.
            </span>
          </div>

          <Section
            title={`Casadas (${preview.matched.length})`}
            accent="emerald"
            testid="bulk-section-matched"
          >
            {preview.matched.length === 0 ? (
              <div className="text-[11px] text-gray-500 italic">Nenhum ticker do extrato bateu com pendência aberta.</div>
            ) : (
              <ul className="space-y-1.5">
                {preview.matched.map(({ ticker, pendency, price, manual }) => (
                  <li
                    key={pendency.id}
                    className="flex items-center justify-between text-[12px]"
                    data-testid={`bulk-matched-${ticker}`}
                  >
                    <div className="font-mono">
                      {ticker} <span className="text-gray-500">— {pendency.asset_name}</span>
                      {pendency.asset_institution_short_name && (
                        <span className="ml-1 text-[10px] uppercase text-gray-400">
                          [{pendency.asset_institution_short_name}]
                        </span>
                      )}
                      {manual && (
                        <span
                          className="ml-1.5 text-[9px] uppercase tracking-wider font-semibold text-indigo-500"
                          title="Mapeamento manual"
                        >
                          🔗 manual
                        </span>
                      )}
                    </div>
                    <div className="tnum text-gray-700 dark:text-gray-300">
                      {fmtBRL(price)}
                      {pendency.previous_unit_price && (
                        <span className="ml-2 text-[10px] text-gray-400">
                          (anterior {fmtBRL(Number(pendency.previous_unit_price))})
                        </span>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </Section>

          <Section
            title={`Pendências não cobertas (${preview.notCovered.length})`}
            accent="gray"
            testid="bulk-section-uncovered"
          >
            {preview.notCovered.length === 0 ? (
              <div className="text-[11px] text-gray-500 italic">Todas as pendências do escopo foram cobertas.</div>
            ) : (
              <ul className="text-[11px] text-gray-500 space-y-0.5">
                {preview.notCovered.map(p => (
                  <li key={p.id}>
                    {p.asset_ticker ?? p.asset_name}
                    {p.asset_institution_short_name && ` · ${p.asset_institution_short_name}`}
                  </li>
                ))}
              </ul>
            )}
          </Section>

          <Section
            title={`Linhas órfãs (${preview.orphan.length})`}
            accent="amber"
            testid="bulk-section-orphan"
          >
            {preview.orphan.length === 0 ? (
              <div className="text-[11px] text-gray-500 italic">Todas as linhas do extrato bateram com algum ativo (ou foram mapeadas manualmente).</div>
            ) : (
              <ul className="space-y-1.5">
                {preview.orphan.map(o => {
                  // tickerOf returns ticker_normalized OR ticker_raw; we need the raw
                  // key to persist mapping under whatever LLM put in ticker_raw.
                  const tickerKey = positions.find(p => tickerOf(p) === o.ticker)?.ticker_raw ?? o.ticker
                  // Filter pendency list by FI when set.
                  const candidatePens = openPendencies.filter(p => {
                    if (fiShortName && p.asset_institution_short_name !== fiShortName) return false
                    if (preview.matched.some(m => m.pendency.asset_id === p.asset_id)) return false
                    return true
                  })
                  return (
                    <li
                      key={o.ticker}
                      className="flex items-center gap-2 text-[11px]"
                      data-testid={`bulk-orphan-${o.ticker}`}
                    >
                      <div className="flex-1 min-w-0">
                        <span className="font-mono text-gray-700 dark:text-gray-300">{o.ticker}</span>
                        {o.price != null && (
                          <span className="ml-1 text-gray-500 tnum">— {fmtBRL(o.price)}</span>
                        )}
                      </div>
                      <select
                        value={manualMappings[tickerKey] ?? ''}
                        onChange={e => {
                          const v = e.target.value
                          setManualMappings(prev => {
                            const next = { ...prev }
                            if (v) next[tickerKey] = v
                            else delete next[tickerKey]
                            return next
                          })
                          // Auto-fill price with the best available suggestion,
                          // but ONLY when the LLM actually extracted a usable
                          // value. previous_unit_price=1 is a Notion-backfill
                          // sentinel for previdência/fundos and is not a price
                          // — never suggest it. User types real value.
                          if (v && !manualPrices[tickerKey]) {
                            if (o.price != null && o.price > 1) {
                              const suggested = o.price.toFixed(2).replace('.', ',')
                              setManualPrices(prev => ({ ...prev, [tickerKey]: suggested }))
                            }
                          }
                          if (!v) {
                            setManualPrices(prev => {
                              const next = { ...prev }
                              delete next[tickerKey]
                              return next
                            })
                          }
                        }}
                        className="h-7 px-2 text-[11px] rounded-md border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 max-w-[16rem]"
                        data-testid={`bulk-orphan-map-${o.ticker}`}
                      >
                        <option value="">— Ignorar (órfã) —</option>
                        {candidatePens.map(p => (
                          <option key={p.id} value={p.id}>
                            {(p.asset_ticker ?? p.asset_name)}
                            {p.asset_institution_short_name ? ` · ${p.asset_institution_short_name}` : ''}
                          </option>
                        ))}
                      </select>
                      {/* Spec 49 hotfix — input de preço SEMPRE aparece
                          quando mapeado. Pré-preenche com preço extraído
                          (se houver) ou com preço anterior da pendência
                          mapeada como sugestão. */}
                      {manualMappings[tickerKey] && (() => {
                        const targetPen = openPendencies.find(p => p.id === manualMappings[tickerKey])
                        const suggested =
                          (o.price != null && o.price > 0
                            ? o.price.toFixed(2).replace('.', ',')
                            : null)
                          ?? (targetPen?.previous_unit_price
                              ? Number(targetPen.previous_unit_price).toFixed(2).replace('.', ',')
                              : null)
                        const current = manualPrices[tickerKey] ?? ''
                        const showsSuggestion = !current && !!suggested
                        return (
                          <input
                            type="text"
                            inputMode="decimal"
                            placeholder={suggested ?? 'Preço'}
                            value={current}
                            onChange={e => {
                              const v = e.target.value
                              setManualPrices(prev => {
                                const next = { ...prev }
                                if (v.trim()) next[tickerKey] = v
                                else delete next[tickerKey]
                                return next
                              })
                            }}
                            className={`h-7 w-28 px-2 text-[11px] rounded-md border text-right tnum focus:outline-none ${
                              o.price == null
                                ? 'border-amber-300 dark:border-amber-700 bg-amber-50 dark:bg-amber-900/20 focus:border-amber-500'
                                : 'border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 focus:border-indigo-500'
                            }`}
                            data-testid={`bulk-orphan-price-${o.ticker}`}
                            title={
                              o.price == null
                                ? `Sem preço no extrato — informe manualmente${showsSuggestion ? ` (sugestão: ${suggested})` : ''}`
                                : `Sobrescrever preço extraído (${fmtBRL(o.price)})`
                            }
                          />
                        )
                      })()}
                    </li>
                  )
                })}
              </ul>
            )}
          </Section>

          {error && (
            <div className="text-[12px] text-red-600 dark:text-red-400">{error}</div>
          )}
        </div>

        <div className="px-5 py-3 border-t border-gray-200 dark:border-gray-800 flex items-center justify-between">
          <button
            onClick={handleCancel}
            disabled={applying}
            className="h-8 px-3 inline-flex items-center gap-1.5 rounded-lg text-[12px] bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700 disabled:opacity-50"
          >
            Cancelar
          </button>
          <button
            onClick={handleApply}
            disabled={applying || preview.matched.length === 0}
            className="h-9 px-4 inline-flex items-center gap-1.5 rounded-lg text-[13px] font-medium bg-emerald-500 hover:bg-emerald-400 disabled:opacity-50 disabled:cursor-not-allowed text-white"
            data-testid="bulk-review-apply"
          >
            {applying
              ? 'Aplicando…'
              : `Aplicar ${preview.matched.length} resoluç${preview.matched.length === 1 ? 'ão' : 'ões'}`}
          </button>
        </div>
      </div>
    </div>
  )
}

function Section({
  title, accent, children, testid,
}: {
  title: string
  accent: 'emerald' | 'amber' | 'gray'
  children: React.ReactNode
  testid?: string
}) {
  const border =
    accent === 'emerald' ? 'border-emerald-500/30'
    : accent === 'amber' ? 'border-amber-500/30'
    : 'border-gray-200 dark:border-gray-700'
  const bg =
    accent === 'emerald' ? 'bg-emerald-500/[0.04]'
    : accent === 'amber' ? 'bg-amber-500/[0.04]'
    : 'bg-gray-50 dark:bg-gray-800/40'
  return (
    <div
      className={`rounded-lg border ${border} ${bg} p-3`}
      data-testid={testid}
    >
      <div className="text-[12px] font-semibold mb-1.5">{title}</div>
      {children}
    </div>
  )
}
