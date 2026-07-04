/* Spec 58 Stage 4 — Bulk income (proventos) review modal.
 *
 * Opens after a BROKER_INCOME extraction completes. Shows three buckets:
 *   - Aplicar (matched_or_lending): vão virar Distribution rows.
 *   - Já registrados (duplicates): external_id já existe na base.
 *   - Órfãs (ticker não casou com ativo da FI): user resolve manual.
 *
 * Diferente do BulkExtractReviewModal (que mexe em pendências de preço),
 * aqui o apply CRIA Distribution rows — não há "casar com pendência".
 */
import { useEffect, useState } from 'react'
import { Sparkles, X } from 'lucide-react'

import { api, type BulkExtractJobOut } from '../lib/api'
import { useEscapeKey } from '../lib/useEscapeKey'


interface Props {
  job: BulkExtractJobOut
  onApplied: (appliedCount: number) => void
  onClose: () => void
}

function fmtMoney(n: number, currency: string): string {
  if (!Number.isFinite(n)) return '—'
  return n.toLocaleString('pt-BR', { style: 'currency', currency })
}

const TYPE_LABEL: Record<string, string> = {
  DIVIDEND: 'Dividendo',
  INTEREST: 'Cupom/Juros',
  JCP: 'JCP',
  SECURITIES_LENDING: 'Aluguel',
}

interface IncomeRow {
  external_id: string
  event_date: string
  ticker: string | null
  asset_id: string | null
  asset_name: string | null
  type: string
  gross_amount: string
  tax_amount: string | null
  net_amount: string
  currency: string
  institution_short_name: string | null
  distribution_id?: string
}

interface IncomePreview {
  applied: IncomeRow[]
  matched_no_pendency: IncomeRow[]  // repurposed as DUPLICATES
  orphan: IncomeRow[]
  pendency_not_in_extract: unknown[]  // unused for income
  auto_skipped: unknown[]             // unused for income
}

export default function BulkIncomeReviewModal({
  job, onApplied, onClose,
}: Props) {
  useEscapeKey(onClose)
  const [preview, setPreview] = useState<IncomePreview | null>(null)
  const [loading, setLoading] = useState(true)
  const [applying, setApplying] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const scopedFi = job.institution_short_name ?? null

  // Período do fechamento em revisão. Mês do period_end (ex.: "2026-06-30"
  // → 2026-06-01..2026-06-30). Preview filtra o payload por isso — CSVs
  // de proventos costumam vir com múltiplos meses; o backend também
  // descarta o que está fora em `_classify_bulk_income`, então mostrar
  // fora aqui era enganoso ("Registrar 45" mas só 1 entrava).
  const periodEndIso = job.snapshot_period_end_date ?? null
  const [periodStartIso, periodStartLabel, periodEndLabel] = (() => {
    if (!periodEndIso) return [null, null, null] as const
    const start = `${periodEndIso.slice(0, 7)}-01`
    return [start, start, periodEndIso] as const
  })()
  const [outOfPeriodCount, setOutOfPeriodCount] = useState(0)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    const events = (job.extracted_json as { events?: unknown[] } | null)?.events ?? []
    const inPeriod: IncomeRow[] = []
    let dropped = 0
    for (const e of events) {
      const row = e as IncomeRow
      const d = row.event_date
      if (periodStartIso && periodEndIso && (d < periodStartIso || d > periodEndIso)) {
        dropped++
        continue
      }
      inPeriod.push({
        ...row,
        external_id: '',
        asset_id: null,
        asset_name: null,
        institution_short_name: scopedFi,
      })
    }
    if (cancelled) return
    setPreview({
      applied: inPeriod,
      matched_no_pendency: [],
      orphan: [],
      pendency_not_in_extract: [],
      auto_skipped: [],
    })
    setOutOfPeriodCount(dropped)
    setLoading(false)
    return () => { cancelled = true }
  }, [job.extracted_json, scopedFi, periodStartIso, periodEndIso])

  async function handleApply() {
    setApplying(true); setError(null)
    try {
      const result = await api.confirmExtraction(job.id, {})
      onApplied(result.applied_count)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Erro')
      setApplying(false)
    }
  }

  function handleCancel() {
    // Fecha otimisticamente; reject vai em fire-and-forget.
    onClose()
    void api.rejectExtraction(job.id, 'descartado pelo usuário')
      .catch(() => { /* best-effort */ })
  }

  const rows = preview?.applied ?? []
  const totalGross = rows.reduce((s, r) => s + Number(r.gross_amount || 0), 0)
  const totalNet = rows.reduce((s, r) => s + Number(r.net_amount || 0), 0)
  const currency = rows[0]?.currency ?? 'USD'

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/60 p-4">
      <div className="w-full max-w-3xl bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-700 shadow-2xl flex flex-col max-h-[90vh]">
        <div className="px-5 py-3 border-b border-gray-200 dark:border-gray-800 flex items-center justify-between">
          <div>
            <div className="text-sm font-semibold text-gray-900 dark:text-white">
              Revisar proventos
            </div>
            <div className="text-[11px] text-gray-500 flex items-center gap-1">
              <Sparkles className="w-3 h-3 text-emerald-500" />
              {rows.length} evento{rows.length === 1 ? '' : 's'} pra registrar
              {scopedFi && <span className="ml-1">· {scopedFi}</span>}
              {periodStartLabel && periodEndLabel && (
                <span className="ml-1 text-gray-600 dark:text-gray-400">
                  · período {periodStartLabel} a {periodEndLabel}
                </span>
              )}
            </div>
            {outOfPeriodCount > 0 && (
              <div className="text-[11px] text-amber-600 dark:text-amber-400 mt-0.5">
                {outOfPeriodCount} evento{outOfPeriodCount === 1 ? '' : 's'} fora do mês
                {' '}ignorado{outOfPeriodCount === 1 ? '' : 's'}.
              </div>
            )}
          </div>
          <button
            onClick={handleCancel}
            className="w-7 h-7 inline-flex items-center justify-center rounded-md text-gray-400 hover:text-gray-700 dark:hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800"
            aria-label="Fechar"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="p-5 overflow-y-auto flex-1 space-y-3">
          {loading ? (
            <div className="text-[12px] text-gray-500 italic">Carregando…</div>
          ) : rows.length === 0 ? (
            <div className="text-[12px] text-gray-500 italic">
              Nenhum provento encontrado no arquivo.
            </div>
          ) : (
            <>
              <div className="flex items-center justify-between text-[11px] text-gray-500 border-b border-gray-200 dark:border-gray-800 pb-1.5">
                <span>Data · Tipo · Ticker</span>
                <span>Bruto / Imposto / Líquido</span>
              </div>
              <ul className="space-y-1">
                {rows.map((r, i) => (
                  <li
                    key={`${r.event_date}-${r.ticker ?? '_'}-${r.type}-${i}`}
                    className="flex items-center justify-between text-[12px] py-1 border-b border-gray-100 dark:border-gray-800/60"
                    data-testid={`income-row-${i}`}
                  >
                    <div className="flex-1 min-w-0">
                      <span className="font-mono text-gray-500 tnum">{r.event_date}</span>
                      <span className="ml-2 text-[10px] uppercase tracking-wider text-emerald-600 dark:text-emerald-400">
                        {TYPE_LABEL[r.type] ?? r.type}
                      </span>
                      <span className="ml-2 font-mono text-gray-700 dark:text-gray-300">
                        {r.ticker ?? '—'}
                      </span>
                    </div>
                    <div className="tnum text-[11px] text-gray-600 dark:text-gray-400">
                      {fmtMoney(Number(r.gross_amount), r.currency)}
                      {r.tax_amount && (
                        <span className="text-red-500 ml-1.5">
                          − {fmtMoney(Number(r.tax_amount), r.currency)}
                        </span>
                      )}
                      <span className="text-gray-900 dark:text-white font-medium ml-1.5">
                        = {fmtMoney(Number(r.net_amount), r.currency)}
                      </span>
                    </div>
                  </li>
                ))}
              </ul>
              <div className="flex items-center justify-between pt-2 text-[12px] border-t border-gray-200 dark:border-gray-800">
                <span className="text-gray-500">Total</span>
                <span className="tnum">
                  Bruto {fmtMoney(totalGross, currency)} ·{' '}
                  <span className="font-semibold">Líquido {fmtMoney(totalNet, currency)}</span>
                </span>
              </div>
              <div className="text-[11px] text-gray-500 italic mt-2">
                Itens já registrados (mesma data + ticker + valor) são pulados
                automaticamente.
              </div>
            </>
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
          <button
            onClick={handleApply}
            disabled={applying || rows.length === 0}
            className="h-9 px-4 inline-flex items-center gap-1.5 rounded-lg text-[13px] font-medium bg-emerald-500 hover:bg-emerald-400 disabled:opacity-50 disabled:cursor-not-allowed text-white"
            data-testid="income-review-apply"
          >
            {applying
              ? 'Registrando…'
              : `Registrar ${rows.length} provento${rows.length === 1 ? '' : 's'}`}
          </button>
        </div>
      </div>
    </div>
  )
}
