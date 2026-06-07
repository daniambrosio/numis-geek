/* Spec 48 — Bulk extract review modal.
 *
 * Opens after BulkUploadZone completes extraction. Shows 4 sections:
 *   - Casadas (will resolve)
 *   - Pendências não cobertas no extrato (info only)
 *   - Linhas órfãs (ticker not in workspace — needs manual map or ignore)
 *   - Ignoradas automaticamente (auto-priced — Spec 57; collapsed)
 *
 * Optional FI dropdown — picks the FI to scope matching to. V1: this is
 * passed as metadata to confirmExtraction; the backend filters matches.
 *
 * Spec 57 follow-up — classification comes from the backend preview
 * endpoint so the modal shows exactly what confirm will do (instead of
 * a divergent client-side guess that didn't know about auto-priced
 * skip).
 */
import { useEffect, useMemo, useState } from 'react'
import { ChevronDown, ChevronRight, Sparkles, X } from 'lucide-react'

import {
  api,
  type BulkApplyDetailOut,
  type BulkExtractJobOut,
  type FinancialInstitutionOut,
  type SnapshotPendencyOut,
} from '../lib/api'
import { useEscapeKey } from '../lib/useEscapeKey'

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

function fmtMoney(n: number | null | undefined, currency: string | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return '—'
  const ccy = (currency || 'BRL').toUpperCase()
  // pt-BR locale shows USD as "US$ 1.234,56" — matches the rest of the app.
  return n.toLocaleString('pt-BR', { style: 'currency', currency: ccy })
}

function tickerOf(pos: ExtractedPosition): string | null {
  return pos.ticker_normalized || pos.ticker_raw || null
}

export default function BulkExtractReviewModal({
  job, pendencies, onApplied, onClose,
}: Props) {
  useEscapeKey(onClose)
  const [fis, setFis] = useState<FinancialInstitutionOut[]>([])
  // Spec 58 — when the job was created scoped to a FI, that's the source
  // of truth and the dropdown is hidden. User can't override here.
  const scopedFiShortName = job.institution_short_name ?? null
  const [fiShortName, setFiShortName] = useState<string>(scopedFiShortName ?? '')
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

  const openPendencies = useMemo(
    () => pendencies.filter(p => !p.resolved_at),
    [pendencies],
  )
  const pendencyById = useMemo(
    () => new Map(openPendencies.map(p => [p.id, p])),
    [openPendencies],
  )

  // Spec 57 follow-up — server-authoritative classification. Re-fetched
  // whenever the user changes FI scope or manual mapping; debouncing is
  // overkill since the call is local + read-only.
  const [serverDetail, setServerDetail] = useState<BulkApplyDetailOut | null>(null)
  const [previewLoading, setPreviewLoading] = useState(true)
  useEffect(() => {
    let cancelled = false
    setPreviewLoading(true)
    api.previewExtraction(job.id, {
      institution_short_name: fiShortName || null,
      manual_mappings: Object.keys(manualMappings).length ? manualMappings : null,
    })
      .then(r => {
        if (cancelled) return
        setServerDetail(r.bulk_detail ?? null)
        setPreviewLoading(false)
      })
      .catch(() => {
        if (cancelled) return
        // Keep last good state; surface as error so user knows preview is stale.
        setPreviewLoading(false)
        setError('Não consegui carregar a prévia. Tente reabrir.')
      })
    return () => { cancelled = true }
  }, [job.id, fiShortName, manualMappings])

  // Adapt server payload to the shape the renderer expects. `matched`
  // pairs each applied row with its pendency object (looked up from
  // openPendencies by id). `price` reflects the unit_price the backend
  // would use (extracted or manual override); NaN signals "no price yet".
  const preview = useMemo(() => {
    const matched: Array<{ ticker: string; pendency: SnapshotPendencyOut; price: number; currency: string | null; manual: boolean }> = []
    const orphan: Array<{ ticker: string; price: number | null; currency: string | null }> = []
    const notCovered: SnapshotPendencyOut[] = []
    const autoSkipped: Array<{ ticker: string; asset_name: string; currency: string | null; institution: string | null; price_source: string }> = []
    if (serverDetail) {
      for (const a of serverDetail.applied) {
        const pen = pendencyById.get(a.pendency_id)
        if (!pen) continue
        const tickerKey = positions.find(p => tickerOf(p) === a.ticker)?.ticker_raw ?? (a.ticker ?? '')
        matched.push({
          ticker: a.ticker ?? '',
          pendency: pen,
          price: Number(a.new_price),
          currency: a.currency,
          manual: !!manualMappings[tickerKey],
        })
      }
      for (const o of serverDetail.orphan) {
        orphan.push({
          ticker: o.ticker,
          price: o.unit_price != null ? Number(o.unit_price) : null,
          currency: o.currency,
        })
      }
      for (const m of serverDetail.matched_no_pendency) {
        // Treated as orphan from the user's perspective — same dropdown to
        // map manually. Backend ignores them otherwise.
        orphan.push({
          ticker: m.ticker ?? '',
          price: m.unit_price != null ? Number(m.unit_price) : null,
          currency: m.currency,
        })
      }
      for (const p of serverDetail.pendency_not_in_extract) {
        const pen = pendencyById.get(p.pendency_id)
        if (pen) notCovered.push(pen)
      }
      for (const s of serverDetail.auto_skipped) {
        autoSkipped.push({
          ticker: s.ticker ?? '',
          asset_name: s.asset_name,
          currency: s.currency,
          institution: s.institution_short_name,
          price_source: s.price_source,
        })
      }
    }
    return { matched, orphan, notCovered, autoSkipped }
  }, [serverDetail, pendencyById, positions, manualMappings])

  const [autoSkippedOpen, setAutoSkippedOpen] = useState(false)

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
              {scopedFiShortName ? 'Extrato de:' : 'Esse extrato é da:'}
            </label>
            {scopedFiShortName ? (
              <span
                className="h-8 px-2.5 inline-flex items-center text-[12px] font-medium rounded-md bg-indigo-500/10 text-indigo-700 dark:text-indigo-300 border border-indigo-500/30"
                data-testid="bulk-review-fi-fixed"
              >
                {scopedFiShortName}
              </span>
            ) : (
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
            )}
            {!scopedFiShortName && (
              <span className="text-[11px] text-gray-500">
                Filtra o matching: só pendências dessa FI serão resolvidas.
              </span>
            )}
            {previewLoading && (
              <span className="text-[11px] text-gray-400 italic">recalculando…</span>
            )}
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
                {preview.matched.map(({ ticker, pendency, price, currency, manual }) => {
                  const tickerKey = positions.find(p => tickerOf(p) === ticker)?.ticker_raw ?? ticker
                  const hasExtractPrice = Number.isFinite(price) && price > 0
                  const manualPrice = manualPrices[tickerKey]
                  const needsPrice = !hasExtractPrice && !manualPrice
                  // Currency hierarchy: applied row → pendency's asset → BRL default.
                  const ccy = currency ?? pendency.asset_currency ?? 'BRL'
                  return (
                    <li
                      key={pendency.id}
                      className={`flex items-center gap-2 text-[12px] ${needsPrice ? 'bg-red-500/[0.04] border border-red-500/30 rounded p-1.5' : ''}`}
                      data-testid={`bulk-matched-${ticker}`}
                    >
                      <div className="flex-1 min-w-0 font-mono">
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
                        {needsPrice && (
                          <span className="ml-1.5 text-[9px] uppercase tracking-wider font-semibold text-red-500">
                            sem preço
                          </span>
                        )}
                      </div>
                      {hasExtractPrice && !manualPrice && (
                        <div className="tnum text-gray-700 dark:text-gray-300 shrink-0">
                          {fmtMoney(price, ccy)}
                          {pendency.previous_unit_price && (
                            <span className="ml-2 text-[10px] text-gray-400">
                              (anterior {fmtMoney(Number(pendency.previous_unit_price), ccy)})
                            </span>
                          )}
                        </div>
                      )}
                      {(needsPrice || manualPrice) && (
                        <input
                          type="text"
                          inputMode="decimal"
                          placeholder={
                            pendency.previous_unit_price
                              ? `Anterior: ${fmtMoney(Number(pendency.previous_unit_price), ccy)}`
                              : 'Preço (ex 1.234,56)'
                          }
                          value={manualPrice ?? ''}
                          onChange={e => {
                            const v = e.target.value
                            setManualPrices(prev => {
                              const next = { ...prev }
                              if (v.trim()) next[tickerKey] = v
                              else delete next[tickerKey]
                              return next
                            })
                          }}
                          autoFocus={needsPrice && preview.matched.length === 1}
                          className={`h-7 w-36 px-2 text-[11px] rounded-md border text-right tnum focus:outline-none ${
                            needsPrice
                              ? 'border-red-400 dark:border-red-700 bg-white dark:bg-gray-800 focus:border-red-500'
                              : 'border-amber-300 dark:border-amber-700 bg-amber-50 dark:bg-amber-900/20 focus:border-amber-500'
                          }`}
                          data-testid={`bulk-matched-price-${ticker}`}
                        />
                      )}
                    </li>
                  )
                })}
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
                          <span className="ml-1 text-gray-500 tnum">— {fmtMoney(o.price, o.currency ?? 'BRL')}</span>
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
                                : `Sobrescrever preço extraído (${fmtMoney(o.price, o.currency ?? 'BRL')})`
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

          {preview.autoSkipped.length > 0 && (
            <div
              className="rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50/60 dark:bg-gray-800/30"
              data-testid="bulk-section-auto-skipped"
            >
              <button
                type="button"
                onClick={() => setAutoSkippedOpen(o => !o)}
                className="w-full px-3 py-2 flex items-center gap-2 text-left"
              >
                {autoSkippedOpen
                  ? <ChevronDown className="w-3.5 h-3.5 text-gray-400" />
                  : <ChevronRight className="w-3.5 h-3.5 text-gray-400" />}
                <span className="text-[12px] font-semibold text-gray-700 dark:text-gray-300">
                  Ignoradas automaticamente ({preview.autoSkipped.length})
                </span>
                <span className="text-[11px] text-gray-500">
                  — ativos com preço gerenciado por API, extrato não toca
                </span>
              </button>
              {autoSkippedOpen && (
                <ul className="px-3 pb-3 text-[11px] text-gray-500 space-y-0.5">
                  {preview.autoSkipped.map(s => (
                    <li key={`${s.ticker}-${s.asset_name}`}>
                      <span className="font-mono text-gray-600 dark:text-gray-400">{s.ticker}</span>
                      <span className="ml-1">— {s.asset_name}</span>
                      {s.institution && <span className="ml-1 text-gray-400">· {s.institution}</span>}
                      <span className="ml-1.5 text-[10px] uppercase tracking-wider text-gray-400">
                        [{s.price_source}]
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}

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
          {(() => {
            // Conta apenas casadas que VÃO efetivamente aplicar: tem preço
            // extraído > 0, ou override manual válido. Botão reflete isso.
            const applicable = preview.matched.filter(({ ticker, price }) => {
              if (Number.isFinite(price) && price > 0) return true
              const tickerKey = positions.find(p => tickerOf(p) === ticker)?.ticker_raw ?? ticker
              const raw = (manualPrices[tickerKey] ?? '').trim()
              if (!raw) return false
              const n = Number(raw.replace(/\./g, '').replace(',', '.'))
              return Number.isFinite(n) && n > 0
            }).length
            const blocked = applying || applicable === 0
            const missing = preview.matched.length - applicable
            return (
              <button
                onClick={handleApply}
                disabled={blocked}
                title={
                  missing > 0
                    ? `${missing} linha${missing === 1 ? '' : 's'} sem preço — preencha pra liberar Aplicar`
                    : undefined
                }
                className="h-9 px-4 inline-flex items-center gap-1.5 rounded-lg text-[13px] font-medium bg-emerald-500 hover:bg-emerald-400 disabled:opacity-50 disabled:cursor-not-allowed text-white"
                data-testid="bulk-review-apply"
              >
                {applying
                  ? 'Aplicando…'
                  : `Aplicar ${applicable} resoluç${applicable === 1 ? 'ão' : 'ões'}${missing > 0 ? ` · ${missing} sem preço` : ''}`}
              </button>
            )
          })()}
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
