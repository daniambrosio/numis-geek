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
import { ACTION_LABEL, applyLabel, countDecisions, groupMates, initialDecisions, originalLabel } from '../lib/bankImport'
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
  { key: 'blocked', label: 'Não importáveis', hint: 'moeda sem cotação pra converter — lance à mão' },
]

const DUP_REASON: Record<string, string> = {
  fingerprint: 'mesma data, valor e descrição',
  installment: 'mesma parcela de compra parcelada',
  invoice_payment_tx: 'pagamento de fatura já lançado',
  in_file: 'linha idêntica no mesmo arquivo',
  possible_duplicate: 'possível duplicata (mesmo valor ±2 dias, de outro arquivo)',
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
  const [preview, setPreview] = useState<BankImportPreview | null>(null)
  const [loadError, setLoadError] = useState('')
  const [parties, setParties] = useState<PartyOut[]>([])
  const [decisions, setDecisions] = useState<Record<string, BankImportDecision>>({})
  const [collapsed, setCollapsed] = useState<Partial<Record<BankImportBucket, boolean>>>({})
  const [applying, setApplying] = useState(false)
  const [discarding, setDiscarding] = useState(false)
  const [toast, setToast] = useState('')
  // última edição de categoria/fornecedor → oferece aplicar às linhas iguais
  const [lastEdit, setLastEdit] = useState<{ rowId: string; patch: Partial<BankImportDecision> } | null>(null)

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

  // Pagamento de fatura só sai de conta na moeda da fatura (audit 2026-10-31).
  const checking = useMemo(() => accounts.filter(a => a.account_type === 'checking' && a.is_active), [accounts])
  const counts = countDecisions(decisions)
  const { toImport, toReconcile } = counts
  const isCard = job.source_hint === 'CARD_INVOICE'

  function setDecision(rowId: string, patch: Partial<BankImportDecision>) {
    setDecisions(prev => ({ ...prev, [rowId]: { ...prev[rowId], ...patch } }))
  }

  const missingAccount = preview?.rows.some(r =>
    decisions[r.row_id]?.action === 'pay' && r.invoice_payment?.kind === 'card_payment_line'
    && !decisions[r.row_id]?.payment_account_id) ?? false

  // X / ESC não fecham com o apply ou o descarte em voo — o resultado
  // (ou o erro) precisa chegar a esta tela.
  const busy = applying || discarding
  const safeClose = () => { if (!busy) onClose() }
  useEscapeKey(safeClose)

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
              {preview?.invoice?.existing_payment && (
                <span className="text-emerald-600 dark:text-emerald-400" data-testid="invoice-existing-payment">
                  · pagamento já lançado em {fmtDay(preview.invoice.existing_payment.event_date)}
                  {preview.invoice.existing_payment.account_name && <> ({preview.invoice.existing_payment.account_name})</>} — será vinculado, sem novo débito
                </span>
              )}
            </div>
          </div>
          <button onClick={safeClose} disabled={busy} aria-label="Fechar"
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
                              onChange={patch => {
                                setDecision(r.row_id, patch)
                                const shared: Partial<BankImportDecision> = {}
                                for (const k of ['category_id', 'party_id', 'no_party', 'new_party_name'] as const) {
                                  if (k in patch) (shared as Record<string, unknown>)[k] = patch[k]
                                }
                                setLastEdit(Object.keys(shared).length ? { rowId: r.row_id, patch: shared } : null)
                              }}
                              mates={lastEdit?.rowId === r.row_id ? groupMates(preview.rows, r) : []}
                              onApplyToMates={() => {
                                if (!lastEdit) return
                                for (const m of groupMates(preview.rows, r)) setDecision(m.row_id, lastEdit.patch)
                                setLastEdit(null)
                              }}
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
              {applyLabel(counts)}
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

const KIND_LABEL: Record<string, string> = { EXPENSE: 'Despesa', INCOME: 'Receita', TRANSFER: 'Transferência' }
const KIND_CLS: Record<string, string> = {
  EXPENSE: 'text-rose-600 dark:text-rose-400',
  INCOME: 'text-emerald-600 dark:text-emerald-400',
  TRANSFER: 'text-sky-600 dark:text-sky-400',
}
const SELECT_CLS = 'h-7 px-2 rounded-md bg-gray-100 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 text-[11px] text-gray-900 dark:text-white focus:outline-none focus:border-indigo-500'

function RowView({ r, decision, onChange, mates, onApplyToMates, categories, parties, checking }: {
  r: BankImportRow
  decision: BankImportDecision
  onChange: (patch: Partial<BankImportDecision>) => void
  mates: BankImportRow[]
  onApplyToMates: () => void
  categories: CategoryOut[]
  parties: PartyOut[]
  checking: AccountOut[]
}) {
  const amount = Number(r.amount)
  const creates = decision.action === 'import' || decision.action === 'import_anyway' || decision.action === 'settle'
  const partyValue = decision.no_party ? 'none' : decision.party_id ? `p:${decision.party_id}`
    : decision.new_party_name != null ? '__custom__' : 'suggested'
  const chosenOcc = r.scheduled?.candidates.find(c => c.occurrence_id === decision.occurrence_id)
  const suggestedLabel = r.party.from_occurrence
    ? `${chosenOcc?.party_name ?? 'Sem fornecedor/cliente'} (da conta a pagar/receber)`
    : r.party.mode === 'existing' ? r.party.party_name
    : r.party.mode === 'new' ? `nova: ${r.party.new_party_name}` : 'Sem fornecedor/cliente'
  const ip = r.invoice_payment
  const sug = r.category_suggestion
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
              {r.duplicate.reason === 'possible_duplicate' && r.duplicate.description && (
                <> · já existe: {fmtDay(r.duplicate.event_date)} "{r.duplicate.description}"</>
              )}
            </span>
          )}
          {ip?.existing_debit && (
            <span>débito já lançado em {fmtDay(ip.existing_debit.event_date)} — vincula sem debitar de novo</span>
          )}
          {ip && ip.invoice_id && (
            <span>fatura {ip.card_name} · fecha {fmtDay(ip.close_date)}{ip.status === 'PAID' ? ' · já paga' : ''}</span>
          )}
          {r.warning && <span className="text-amber-600 dark:text-amber-400">{r.warning}</span>}
          {r.scheduled && decision.action !== 'settle' && r.scheduled.candidates[0] && (
            <span className="text-indigo-600 dark:text-indigo-300" data-testid={`candidate-${r.row_id}`}
              title={(r.scheduled.candidates[0].signals ?? []).join(' · ')}>
              Possível conta: {r.scheduled.candidates[0].description} · vence {fmtDay(r.scheduled.candidates[0].due_date)}
              {r.scheduled.candidates.length > 1 && ` (+${r.scheduled.candidates.length - 1})`} — escolha "{ACTION_LABEL.settle}" para quitar
            </span>
          )}
          {decision.action === 'settle' && chosenOcc?.learns_amount
            && Math.abs(Math.abs(amount) - Number(chosenOcc.amount)) >= 0.005 && (
            <span className="text-indigo-600 dark:text-indigo-300" data-testid={`learns-${r.row_id}`}>
              Atualiza o valor previsto de {fmtMoney(Number(chosenOcc.amount), chosenOcc.currency as 'BRL' | 'USD')} para {fmtMoney(Math.abs(amount), chosenOcc.currency as 'BRL' | 'USD')}
            </span>
          )}
        </div>
      </td>
      <td className={`px-2 py-2 text-right tnum money font-medium whitespace-nowrap ${amount > 0 ? 'text-emerald-500 dark:text-emerald-400' : 'text-gray-900 dark:text-white'}`}>
        {fmtMoney(amount, r.currency as 'BRL' | 'USD', { sign: true })}
        {r.original && (
          <div className="text-[10px] font-normal text-gray-500" data-testid={`original-${r.row_id}`}
            title={`${r.original.rate_source === 'STATEMENT' ? 'cotação do documento' : 'PTAX'} de ${fmtDay(r.original.rate_date)}`}>
            {originalLabel(r.original)}
          </div>
        )}
      </td>
      <td className="px-2 py-2">
        {/* Colunas fixas (categoria · fornecedor · ação) numa linha só; o que
            é extra (nome do novo fornecedor, aplicar às iguais, conta a
            quitar, conta de origem) vai embaixo — antes o flex-wrap jogava
            a ação pra uma segunda linha e desalinhava a tabela. */}
        <div className="grid grid-cols-[12rem_11rem_9rem] gap-1.5 items-start justify-end">
          <div className="min-w-0">
            {creates && (
              <>
                <CategorySelect categories={categories} value={decision.category_id ?? ''}
                  onChange={v => onChange({ category_id: v || null })} />
                {(() => {
                  // Tipo da categoria escolhida à vista: o select corta o nome
                  // ("Débito Transfer Entre Co…") e o user não via que a linha
                  // vai como transferência, fora de despesas/receitas.
                  const cat = decision.category_id ? categories.find(c => c.id === decision.category_id) : undefined
                  const parent = cat?.parent_id ? categories.find(c => c.id === cat.parent_id) : undefined
                  const kind = cat?.kind ?? parent?.kind
                  const label = kind ? KIND_LABEL[kind] : null
                  const isSug = sug && decision.category_id === sug.category_id
                  if (!label && !isSug) return null
                  return (
                    <div className="text-[10px] leading-tight space-x-1" data-testid={`catinfo-${r.row_id}`}>
                      {label && (
                        <span className={KIND_CLS[kind!]} title={parent ? `${parent.name} › ${cat!.name}` : cat?.name}
                          data-testid={`kind-${r.row_id}`}>{label}</span>
                      )}
                      {isSug && (
                        <span className="text-indigo-600 dark:text-indigo-300 cursor-help" title={sug!.reason}
                          data-testid={`suggested-${r.row_id}`}>· sugerida</span>
                      )}
                    </div>
                  )
                })()}
                {sug && !sug.applied && !decision.category_id && (
                  <button type="button" onClick={() => onChange({ category_id: sug.category_id })} title={sug.reason}
                    className="block text-left text-[10px] leading-tight text-gray-500 underline decoration-dotted truncate max-w-full"
                    data-testid={`hint-${r.row_id}`}>
                    sugestão: {sug.path}
                  </button>
                )}
              </>
            )}
          </div>
          <div className="min-w-0">
            {creates && (
              <select value={partyValue} aria-label="Fornecedor/Cliente" className={`${SELECT_CLS} w-full`}
                onChange={e => {
                  const v = e.target.value
                  if (v === 'suggested') onChange({ party_id: null, no_party: false, new_party_name: null })
                  else if (v === 'none') onChange({ party_id: null, no_party: true, new_party_name: null })
                  else if (v === '__custom__') onChange({ party_id: null, no_party: false, new_party_name: r.party.new_party_name ?? r.counterparty ?? r.description })
                  else onChange({ party_id: v.slice(2), no_party: false, new_party_name: null })
                }}>
                <option value="suggested">{suggestedLabel}</option>
                <option value="__custom__">Novo fornecedor/cliente…</option>
                {r.party.mode !== 'none' && <option value="none">Sem fornecedor/cliente</option>}
                {parties.filter(p => p.id !== r.party.party_id).map(p => <option key={p.id} value={`p:${p.id}`}>{p.name}</option>)}
              </select>
            )}
            {/* Nome do novo fornecedor logo abaixo do select dele, mesma
                largura — antes caía na linha de extras, alinhado à direita
                embaixo da ação. */}
            {creates && decision.new_party_name != null && (
              <input type="text" value={decision.new_party_name} aria-label="Nome do novo fornecedor/cliente"
                placeholder="Nome do fornecedor/cliente"
                onChange={e => onChange({ new_party_name: e.target.value })}
                className={`${SELECT_CLS} w-full mt-1`} autoFocus />
            )}
          </div>
          <select value={decision.action} aria-label="Ação" className={`${SELECT_CLS} w-full`} data-testid={`action-${r.row_id}`}
            onChange={e => onChange({ action: e.target.value as BankImportAction })}>
            {r.actions.map(a => <option key={a} value={a}>{ACTION_LABEL[a]}</option>)}
          </select>
        </div>
        <div className="mt-1 flex flex-wrap items-center gap-1.5 justify-end">
          {creates && mates.length > 0 && (
            <button type="button" onClick={onApplyToMates} data-testid={`apply-mates-${r.row_id}`}
              className="text-[10px] text-indigo-600 dark:text-indigo-300 underline">
              aplicar às outras {mates.length} {mates.length === 1 ? 'linha igual' : 'linhas iguais'} neste arquivo
            </button>
          )}
          {decision.action === 'settle' && r.scheduled && (
            <select value={decision.occurrence_id ?? ''} aria-label="Conta a pagar/receber" className={`${SELECT_CLS} max-w-[20rem]`}
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
              {checking.filter(a => a.currency === r.currency).map(a => <option key={a.id} value={a.id}>{a.name}</option>)}
            </select>
          )}
        </div>
      </td>
    </tr>
  )
}
