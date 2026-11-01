/* Spec 71 — revisão do import de extrato (conta corrente) / fatura (cartão).
 *
 * Padrão BulkIncomeReviewModal: a classificação é do servidor
 * (`previewExtraction` → `bank_import`), a mesma que o apply executa. O
 * modal só junta as decisões por linha:
 *
 *   - Novas → Importar | Pular (categoria / fornecedor editáveis);
 *   - Duplicadas → Reconciliar (tx manual nunca reconciliada) | Pular |
 *     Importar mesmo assim;
 *   - Pagamento de fatura → Pagar fatura (pay_invoice) | Reconciliar o
 *     pagamento existente | Pular — a linha "Pagamento recebido" da fatura
 *     nunca vira lançamento do cartão;
 *   - Quita conta a pagar/receber → Marcar pago (settle_occurrence) |
 *     Importar sem quitar | Pular.
 *
 * Fechar (X / ESC) só fecha: o job fica EXTRACTED e o mesmo arquivo reabre
 * a revisão. "Descartar" rejeita o job.
 */
import { useEffect, useMemo, useState } from 'react'
import { AlertTriangle, ChevronDown, ChevronRight, Loader2, Sparkles, X } from 'lucide-react'

import {
  api, type AccountOut, type BankImportAction, type BankImportBucket, type BankImportDecision,
  type BankImportPreview, type BankImportResult, type BankImportRow, type CategoryOut, type PartyOut,
  type StatementImportOut,
} from '../lib/api'
import { ACTION_LABEL, countDecisions, initialDecisions } from '../lib/bankImport'
import { useEscapeKey } from '../lib/useEscapeKey'
import { CategorySelect, fmtMoney } from './TransactionComposers'

interface Props {
  job: StatementImportOut
  accounts: AccountOut[]
  categories: CategoryOut[]
  onApplied: (result: BankImportResult) => void
  onClose: () => void
}

const BUCKETS: { key: BankImportBucket; label: string; hint: string }[] = [
  { key: 'new', label: 'Novas', hint: 'viram movimentações reconciliadas' },
  { key: 'duplicate', label: 'Duplicadas', hint: 'já estão no sistema' },
  { key: 'invoice_payment', label: 'Pagamento de fatura', hint: 'quita a fatura pelo fluxo Pagar fatura' },
  { key: 'scheduled', label: 'Quita conta a pagar/receber', hint: 'marca a conta como paga' },
]

const DUP_REASON: Record<string, string> = {
  fingerprint: 'mesma data, valor e descrição',
  installment: 'mesma parcela de compra parcelada',
  invoice_payment_tx: 'pagamento de fatura já lançado',
  in_file: 'linha idêntica no mesmo arquivo',
}

function fmtDay(iso: string | null | undefined): string {
  if (!iso) return '—'
  const [y, m, d] = iso.split('-')
  return `${d}/${m}/${y.slice(2)}`
}

function fmtDM(iso: string): string {
  const [, m, d] = iso.split('-')
  return `${d}/${m}`
}

export default function BankImportReviewModal({ job, accounts, categories, onApplied, onClose }: Props) {
  useEscapeKey(onClose)
  const [preview, setPreview] = useState<BankImportPreview | null>(null)
  const [loadError, setLoadError] = useState('')
  const [parties, setParties] = useState<PartyOut[]>([])
  const [decisions, setDecisions] = useState<Record<string, BankImportDecision>>({})
  const [collapsed, setCollapsed] = useState<Partial<Record<BankImportBucket, boolean>>>({})
  const [applying, setApplying] = useState(false)
  const [discarding, setDiscarding] = useState(false)
  const [toast, setToast] = useState('')

  useEffect(() => {
    let cancelled = false
    api.previewExtraction(job.id)
      .then(res => {
        if (cancelled) return
        const p = (res.bank_import ?? null) as BankImportPreview | null
        if (!p) { setLoadError('Resposta sem classificação do import.'); return }
        setPreview(p)
        setDecisions(initialDecisions(p.rows))
        // Duplicadas que só vão ser puladas começam recolhidas.
        const dups = p.rows.filter(r => r.bucket === 'duplicate')
        if (dups.length > 0 && dups.every(r => r.default_action === 'skip')) setCollapsed({ duplicate: true })
      })
      .catch(err => { if (!cancelled) setLoadError(err instanceof Error ? err.message : 'Erro ao carregar a revisão.') })
    // Fornecedores pro select — falha não derruba a revisão.
    api.listParties().then(ps => { if (!cancelled) setParties(ps.filter(p => p.is_active)) }).catch(() => {})
    return () => { cancelled = true }
  }, [job.id])

  const checking = useMemo(() => accounts.filter(a => a.account_type === 'checking' && a.is_active), [accounts])
  const { toImport, toReconcile } = countDecisions(decisions)
  const isCard = job.source_hint === 'CARD_INVOICE'

  function setDecision(rowId: string, patch: Partial<BankImportDecision>) {
    setDecisions(prev => ({ ...prev, [rowId]: { ...prev[rowId], ...patch } }))
  }

  const missingAccount = preview?.rows.some(r =>
    decisions[r.row_id]?.action === 'pay' && r.invoice_payment?.kind === 'card_payment_line'
    && !decisions[r.row_id]?.payment_account_id) ?? false

  async function handleApply() {
    setApplying(true)
    try {
      const res = await api.confirmExtraction(job.id, { bank_decisions: decisions })
      onApplied(res.bank_import as BankImportResult)
    } catch (err) {
      setToast(err instanceof Error ? err.message : 'Erro ao importar.')
      setApplying(false)
    }
  }

  async function handleDiscard() {
    setDiscarding(true)
    try {
      await api.rejectExtraction(job.id, 'descartado pelo usuário')
      onClose()
    } catch (err) {
      setToast(err instanceof Error ? err.message : 'Erro ao descartar.')
      setDiscarding(false)
    }
  }

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/60 p-4">
      <div role="dialog" aria-label={isCard ? 'Revisar fatura importada' : 'Revisar extrato importado'}
        className="w-full max-w-5xl bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-700 shadow-2xl flex flex-col max-h-[92vh]">
        <div className="px-5 py-3 border-b border-gray-200 dark:border-gray-800 flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="text-sm font-semibold text-gray-900 dark:text-white">
              {isCard ? 'Revisar fatura' : 'Revisar extrato'}
            </div>
            <div className="text-[11px] text-gray-500 flex items-center gap-1 flex-wrap">
              <Sparkles className="w-3 h-3 text-emerald-500" />
              <span className="truncate">{job.filename ?? 'arquivo'}</span>
              {preview?.period.start && preview.period.end && (
                <span>· período {fmtDay(preview.period.start)} a {fmtDay(preview.period.end)}</span>
              )}
              {preview?.invoice && (
                <span data-testid="invoice-summary">
                  · fecha {fmtDay(preview.invoice.close_date)} · vence {fmtDay(preview.invoice.due_date)}
                  {preview.invoice.total_amount && <> · total {fmtMoney(Number(preview.invoice.total_amount), 'BRL')}</>}
                </span>
              )}
            </div>
          </div>
          <button onClick={onClose} aria-label="Fechar"
            className="w-7 h-7 shrink-0 inline-flex items-center justify-center rounded-md text-gray-400 hover:text-gray-700 dark:hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="p-5 overflow-y-auto flex-1 space-y-3">
          {loadError ? (
            <div className="text-[12px] text-red-600 dark:text-red-400">{loadError}</div>
          ) : !preview ? (
            <div className="text-[12px] text-gray-500 italic flex items-center gap-2"><Loader2 className="w-3.5 h-3.5 animate-spin" /> Carregando…</div>
          ) : (
            <>
              {preview.overlaps.map(o => (
                <div key={o.job_id} data-testid="overlap-banner"
                  className="flex items-center gap-2 text-[12px] rounded-lg px-3 py-2 bg-amber-500/10 text-amber-700 dark:text-amber-300">
                  <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
                  Overlap com import de {fmtDM(o.start)}–{fmtDM(o.end)} — {o.duplicate_count} {o.duplicate_count === 1 ? 'linha caiu' : 'linhas caíram'} como duplicatas
                </div>
              ))}
              {preview.warnings.map((w, i) => (
                <div key={i} className="text-[11px] text-amber-600 dark:text-amber-400">{w}</div>
              ))}
              {preview.rows.length === 0 && (
                <div className="text-[12px] text-gray-500 italic">Nenhuma movimentação encontrada no arquivo.</div>
              )}
              {BUCKETS.map(b => {
                const rows = preview.rows.filter(r => r.bucket === b.key)
                if (rows.length === 0) return null
                const isCollapsed = !!collapsed[b.key]
                return (
                  <section key={b.key} data-testid={`bucket-${b.key}`} className="rounded-xl border border-gray-200 dark:border-gray-800">
                    <button type="button" onClick={() => setCollapsed(c => ({ ...c, [b.key]: !isCollapsed }))}
                      aria-expanded={!isCollapsed}
                      className="w-full flex items-center gap-2 px-3 py-2 text-left text-[12px] font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800/40 rounded-t-xl">
                      {isCollapsed ? <ChevronRight className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
                      {b.label} <span className="text-gray-500 font-normal">· {rows.length} · {b.hint}</span>
                    </button>
                    {!isCollapsed && (
                      <table className="w-full text-[12px]">
                        <tbody>
                          {rows.map(r => (
                            <RowView key={r.row_id} r={r} decision={decisions[r.row_id] ?? { action: r.default_action }}
                              onChange={patch => setDecision(r.row_id, patch)}
                              categories={categories} parties={parties} checking={checking} />
                          ))}
                        </tbody>
                      </table>
                    )}
                  </section>
                )
              })}
            </>
          )}
        </div>

        <div className="px-5 py-3 border-t border-gray-200 dark:border-gray-800 flex items-center justify-between gap-3">
          <button onClick={handleDiscard} disabled={applying || discarding}
            className="h-8 px-3 inline-flex items-center gap-1.5 rounded-lg text-[12px] bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700 disabled:opacity-50">
            {discarding && <Loader2 className="w-3 h-3 animate-spin" />} Descartar
          </button>
          <div className="flex items-center gap-3">
            {missingAccount && <span className="text-[11px] text-amber-600 dark:text-amber-400">Escolha a conta do pagamento de fatura</span>}
            <button onClick={handleApply} disabled={applying || !preview || (toImport + toReconcile === 0) || missingAccount}
              data-testid="bank-import-apply"
              className="h-9 px-4 inline-flex items-center gap-1.5 rounded-lg text-[13px] font-medium bg-emerald-500 hover:bg-emerald-400 disabled:opacity-50 disabled:cursor-not-allowed text-white">
              {applying && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
              Importar {toImport} · Reconciliar {toReconcile}
            </button>
          </div>
        </div>
      </div>
      {toast && (
        <div className="fixed bottom-4 right-4 z-[70] max-w-sm bg-red-600 text-white text-[12px] rounded-lg shadow-lg px-4 py-3" role="alert">
          {toast}
          <button onClick={() => setToast('')} className="ml-3 underline">fechar</button>
        </div>
      )}
    </div>
  )
}

const SELECT_CLS = 'h-7 px-2 rounded-md bg-gray-100 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 text-[11px] text-gray-900 dark:text-white focus:outline-none focus:border-indigo-500'

function RowView({ r, decision, onChange, categories, parties, checking }: {
  r: BankImportRow
  decision: BankImportDecision
  onChange: (patch: Partial<BankImportDecision>) => void
  categories: CategoryOut[]
  parties: PartyOut[]
  checking: AccountOut[]
}) {
  const amount = Number(r.amount)
  const creates = decision.action === 'import' || decision.action === 'import_anyway' || decision.action === 'settle'
  const partyValue = decision.no_party ? 'none' : decision.party_id ? `p:${decision.party_id}` : 'suggested'
  const suggestedLabel = r.party.mode === 'existing' ? r.party.party_name
    : r.party.mode === 'new' ? `nova: ${r.party.new_party_name}` : 'Sem fornecedor/cliente'
  const ip = r.invoice_payment
  return (
    <tr className="border-t border-gray-100 dark:border-gray-800 align-top" data-testid={`row-${r.row_id}`}>
      <td className="px-3 py-2 tnum text-gray-500 whitespace-nowrap">{fmtDay(r.event_date)}</td>
      <td className="px-2 py-2 min-w-[180px]">
        <div className="text-gray-900 dark:text-white">{r.description}</div>
        <div className="text-[10px] text-gray-500 space-x-1">
          {r.installment_total && <span>parc. {r.installment_number}/{r.installment_total} · compra {fmtDay(r.original_date)}</span>}
          {r.duplicate && (
            <span>
              {DUP_REASON[r.duplicate.reason ?? ''] ?? 'duplicada'}
              {r.duplicate.transaction_id && <> · {r.duplicate.is_reconciled ? 'já reconciliada' : 'manual, não reconciliada'}</>}
            </span>
          )}
          {ip && ip.invoice_id && (
            <span>fatura {ip.card_name} · fecha {fmtDay(ip.close_date)}{ip.status === 'PAID' ? ' · já paga' : ''}</span>
          )}
          {r.warning && <span className="text-amber-600 dark:text-amber-400">{r.warning}</span>}
        </div>
      </td>
      <td className={`px-2 py-2 text-right tnum money font-medium whitespace-nowrap ${amount > 0 ? 'text-emerald-500 dark:text-emerald-400' : 'text-gray-900 dark:text-white'}`}>
        {fmtMoney(amount, r.currency as 'BRL' | 'USD', { sign: true })}
      </td>
      <td className="px-2 py-2">
        <div className="flex flex-wrap items-center gap-1.5 justify-end">
          {creates && (
            <>
              <div className="w-40">
                <CategorySelect categories={categories} value={decision.category_id ?? ''}
                  onChange={v => onChange({ category_id: v || null })} />
              </div>
              <select value={partyValue} aria-label="Fornecedor/Cliente" className={`${SELECT_CLS} max-w-[170px]`}
                onChange={e => {
                  const v = e.target.value
                  if (v === 'suggested') onChange({ party_id: null, no_party: false })
                  else if (v === 'none') onChange({ party_id: null, no_party: true })
                  else onChange({ party_id: v.slice(2), no_party: false })
                }}>
                <option value="suggested">{suggestedLabel}</option>
                {r.party.mode !== 'none' && <option value="none">Sem fornecedor/cliente</option>}
                {parties.filter(p => p.id !== r.party.party_id).map(p => <option key={p.id} value={`p:${p.id}`}>{p.name}</option>)}
              </select>
            </>
          )}
          {decision.action === 'settle' && r.scheduled && (
            <select value={decision.occurrence_id ?? ''} aria-label="Conta a pagar/receber" className={`${SELECT_CLS} max-w-[200px]`}
              onChange={e => onChange({ occurrence_id: e.target.value })}>
              {r.scheduled.candidates.map(c => (
                <option key={c.occurrence_id} value={c.occurrence_id}>
                  {c.description} · vence {fmtDay(c.due_date)} · {fmtMoney(Number(c.amount), c.currency as 'BRL' | 'USD')}
                </option>
              ))}
            </select>
          )}
          {decision.action === 'pay' && ip?.kind === 'card_payment_line' && (
            <select value={decision.payment_account_id ?? ''} aria-label="Conta do pagamento" className={`${SELECT_CLS} max-w-[170px]`}
              onChange={e => onChange({ payment_account_id: e.target.value || null })}>
              <option value="">Conta de origem…</option>
              {checking.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}
            </select>
          )}
          <select value={decision.action} aria-label="Ação" className={SELECT_CLS} data-testid={`action-${r.row_id}`}
            onChange={e => onChange({ action: e.target.value as BankImportAction })}>
            {r.actions.map(a => <option key={a} value={a}>{ACTION_LABEL[a]}</option>)}
          </select>
        </div>
      </td>
    </tr>
  )
}
