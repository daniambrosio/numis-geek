/* Spec 58 Stage 4 — Bulk income (proventos) review modal.
 *
 * Opens after a BROKER_INCOME extraction completes. Shows three buckets:
 *   - Aplicar (matched_or_lending): vão virar Distribution rows.
 *   - Já registrados (duplicates): external_id já existe na base.
 *   - Órfãs (ticker não casou com ativo da FI): user resolve manual.
 *
 * Diferente do BulkExtractReviewModal (que mexe em pendências de preço),
 * aqui o apply CRIA Distribution rows — não há "casar com pendência".
 *
 * Server-authoritative (2026-09-05): as três seções vêm de
 * `previewExtraction` (que resolve cada evento pro Asset da FI), não de
 * classificação no cliente. A versão anterior lia `extracted_json` direto
 * com o campo errado (`ticker` em vez de `ticker_raw`) e nunca sabia pra
 * qual ativo o provento ia — mostrava "—" em todas as linhas.
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
  // option_events (compra/venda de opção) usam `option_ticker` no
  // payload em vez de `ticker` — fallback pra não renderizar "—".
  option_ticker?: string | null
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
  errors: string[]
}

/** Nome do ativo pra onde o provento vai. Aluguel (sem ticker) é
 *  permitido sem ativo — Distribution.asset_id é nullable. */
function assetLabel(r: IncomeRow): string | null {
  if (r.asset_name) return r.asset_name
  if (!r.ticker && !r.option_ticker) return 'sem ativo (aluguel)'
  return null
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

  // Período do fechamento em revisão — só pra rótulo; quem filtra os
  // eventos fora do mês é o backend (`_classify_bulk_income`), que
  // devolve a contagem ignorada em `errors`.
  const periodEndIso = job.snapshot_period_end_date ?? null
  const periodStartLabel = periodEndIso ? `${periodEndIso.slice(0, 7)}-01` : null
  const periodEndLabel = periodEndIso

  // `loading` nasce true e o modal é remontado por job — não precisa
  // resetar estado dentro do effect (react-hooks/set-state-in-effect).
  useEffect(() => {
    let cancelled = false
    api.previewExtraction(job.id)
      .then(result => {
        if (cancelled) return
        const detail = (result.bulk_detail ?? null) as unknown as Omit<IncomePreview, 'errors'> | null
        setPreview({
          applied: detail?.applied ?? [],
          matched_no_pendency: detail?.matched_no_pendency ?? [],
          orphan: detail?.orphan ?? [],
          pendency_not_in_extract: [],
          auto_skipped: [],
          errors: result.errors ?? [],
        })
      })
      .catch(e => {
        if (cancelled) return
        setError(e instanceof Error ? e.message : 'Erro ao carregar preview')
        setPreview({
          applied: [], matched_no_pendency: [], orphan: [],
          pendency_not_in_extract: [], auto_skipped: [], errors: [],
        })
      })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [job.id])

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
  const orphans = preview?.orphan ?? []
  const duplicates = preview?.matched_no_pendency ?? []
  const notices = preview?.errors ?? []
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
            {notices.map((n, i) => (
              <div key={i} className="text-[11px] text-amber-600 dark:text-amber-400 mt-0.5">
                {n}
              </div>
            ))}
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
          ) : rows.length === 0 && orphans.length === 0 && duplicates.length === 0 ? (
            <div className="text-[12px] text-gray-500 italic">
              Nenhum provento encontrado no arquivo.
            </div>
          ) : (
            <>
              <div className="flex items-center justify-between text-[11px] text-gray-500 border-b border-gray-200 dark:border-gray-800 pb-1.5">
                <span>Data · Tipo · Ticker · Ativo</span>
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
                        {r.ticker ?? r.option_ticker ?? '—'}
                      </span>
                      <span
                        className="ml-2 text-gray-500 dark:text-gray-400 truncate"
                        data-testid={`income-row-asset-${i}`}
                      >
                        {assetLabel(r) ?? '—'}
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
              {orphans.length > 0 && (
                <div className="mt-3" data-testid="income-orphans">
                  <div className="text-[11px] font-medium text-red-600 dark:text-red-400 mb-1">
                    {orphans.length} sem ativo correspondente na {scopedFi ?? 'instituição'} — não
                    {orphans.length === 1 ? ' será registrado' : ' serão registrados'}
                  </div>
                  <ul className="space-y-1">
                    {orphans.map((r, i) => (
                      <li
                        key={`orphan-${r.event_date}-${r.ticker ?? '_'}-${i}`}
                        className="flex items-center justify-between text-[12px] py-1 border-b border-gray-100 dark:border-gray-800/60"
                      >
                        <div className="flex-1 min-w-0">
                          <span className="font-mono text-gray-500 tnum">{r.event_date}</span>
                          <span className="ml-2 text-[10px] uppercase tracking-wider text-gray-500">
                            {TYPE_LABEL[r.type] ?? r.type}
                          </span>
                          <span className="ml-2 font-mono text-red-600 dark:text-red-400">
                            {r.ticker ?? r.option_ticker ?? '—'}
                          </span>
                        </div>
                        <div className="tnum text-[11px] text-gray-500">
                          {fmtMoney(Number(r.net_amount), r.currency)}
                        </div>
                      </li>
                    ))}
                  </ul>
                  <div className="text-[11px] text-gray-500 italic mt-1">
                    Cadastre o ativo na {scopedFi ?? 'instituição'} e clique em Re-extrair.
                  </div>
                </div>
              )}
              {duplicates.length > 0 && (
                <div className="mt-3" data-testid="income-duplicates">
                  <div className="text-[11px] font-medium text-gray-500 mb-1">
                    {duplicates.length} já registrado{duplicates.length === 1 ? '' : 's'} — pulado{duplicates.length === 1 ? '' : 's'}
                  </div>
                  <ul className="space-y-1 opacity-60">
                    {duplicates.map((r, i) => (
                      <li
                        key={`dup-${r.event_date}-${r.ticker ?? '_'}-${i}`}
                        className="flex items-center justify-between text-[12px] py-1 border-b border-gray-100 dark:border-gray-800/60"
                      >
                        <div className="flex-1 min-w-0">
                          <span className="font-mono text-gray-500 tnum">{r.event_date}</span>
                          <span className="ml-2 text-[10px] uppercase tracking-wider text-gray-500">
                            {TYPE_LABEL[r.type] ?? r.type}
                          </span>
                          <span className="ml-2 font-mono text-gray-600 dark:text-gray-400">
                            {r.ticker ?? r.option_ticker ?? '—'}
                          </span>
                          <span className="ml-2 text-gray-500 truncate">{assetLabel(r) ?? '—'}</span>
                        </div>
                        <div className="tnum text-[11px] text-gray-500">
                          {fmtMoney(Number(r.net_amount), r.currency)}
                        </div>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
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
