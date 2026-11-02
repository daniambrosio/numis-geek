/* Spec 69 — Detalhe do cartão (/credit-cards/:id), fiel ao proto CartaoDetail
 * (index.html:3620-3721): hero com fatura aberta + barra de limite, KPIs,
 * card lateral "Faturas anteriores", navegação entre cartões.
 * Spec 70: KPIs Lançamentos / Compras parceladas / Próx. fatura vêm das tx;
 * tabela "Lançamentos da fatura aberta" é real; "Pagar fatura" nas faturas
 * fechadas (contrato pay_invoice). Spec 71: "Importar fatura" sobe o
 * PDF/print → revisão com dedup; card "Faturas importadas". "Fechar
 * fatura", "Nova fatura" e "Pagar fatura" são deltas declarados (proto não
 * modela o ciclo).
 *
 * "Fatura aberta" = a OPEN de fechamento mais próximo — com parcelas,
 * existem OPEN futuras.
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { Check, CreditCard as CreditCardIcon, Pencil, Plus, Wallet } from 'lucide-react'
import {
  api, type AccountOut, type CategoryOut, type CreditCardOut, type InvoiceOut, type InvoicePayPayload,
  type TransactionCreatePayload, type TransactionOut, type TransactionUpdatePayload, type UserOut,
} from '../lib/api'
import AppLayout from '../components/AppLayout'
import { Card, SectionTitle, FILogo, Field, INPUT_CLS, LoadMore } from '../components/ui'
import { parseDecimal } from '../lib/parseDecimal'
import { useEscapeKey } from '../lib/useEscapeKey'
import { CARDS_CHANGED_EVENT } from '../lib/useCardCounts'
import { fmtMoney, fmtPct } from './CreditCards'
import KpiTile from '../components/KpiTile'
import { CardTxComposer, CategorySelect } from '../components/TransactionComposers'
import { todayISO } from '../lib/format'
import { useTransactionAttachments } from '../lib/useTransactionAttachments'
import BankImportReviewModal from '../components/BankImportReviewModal'
import { ImportButton, ImportHistory } from '../components/BankImport'
import { summarizeResult, useBankImport } from '../lib/bankImport'
import SourceFileClip from '../components/SourceFileClip'

/** Fatura CLOSED cujo total congelado não bate mais com a soma das tx
 * (lançamento entrou/mudou depois do fechamento — import da spec 71). */
export function invoiceDiverges(inv: InvoiceOut): boolean {
  return inv.status === 'CLOSED' && inv.total_amount != null && inv.tx_total != null
    && Math.abs(inv.total_amount - inv.tx_total) >= 0.005
}

function fmtDate(iso: string) {
  const [y, m, d] = iso.split('-')
  return `${d}/${m}/${y.slice(2)}`
}

function HBar({ value, max, height = 6 }: { value: number; max: number; height?: number }) {
  const pct = max > 0 ? Math.min(value / max, 1) : 0
  const color = pct > 0.8 ? '#ef4444' : pct > 0.5 ? '#f59e0b' : '#22c55e'
  return (
    <div className="w-full rounded-full bg-gray-100 dark:bg-gray-800" style={{ height }}>
      <div className="rounded-full transition-all" style={{ width: `${pct * 100}%`, height, background: color }} />
    </div>
  )
}

const STATUS_META: Record<InvoiceOut['status'], { label: string; cls: string }> = {
  OPEN: { label: 'Aberta', cls: 'bg-amber-500/15 text-amber-600 dark:text-amber-400' },
  CLOSED: { label: 'Fechada', cls: 'bg-blue-500/15 text-blue-600 dark:text-blue-400' },
  PAID: { label: 'Paga', cls: 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400' },
}

export default function CreditCardDetail() {
  const navigate = useNavigate()
  const { id } = useParams<{ id: string }>()
  const [me, setMe] = useState<UserOut | null>(null)
  const [cards, setCards] = useState<CreditCardOut[]>([])
  const [invoices, setInvoices] = useState<InvoiceOut[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [newInvoiceOpen, setNewInvoiceOpen] = useState(false)
  const [closingInvoice, setClosingInvoice] = useState<InvoiceOut | null>(null)
  const [payingInvoice, setPayingInvoice] = useState<InvoiceOut | null>(null)
  const [actionError, setActionError] = useState('')
  const [notice, setNotice] = useState('')
  const imports = useBankImport('card', id, setActionError)
  // Lançamentos da fatura aberta — filtrados no servidor por invoice_id
  // (antes: todas as tx do cartão, cortadas em 500 sem aviso).
  const [txs, setTxs] = useState<TransactionOut[]>([])
  const [txTotal, setTxTotal] = useState(0)
  const [txPage, setTxPage] = useState(1)
  const [loadingMore, setLoadingMore] = useState(false)
  const attachments = useTransactionAttachments()
  const [accounts, setAccounts] = useState<AccountOut[]>([])
  const [categories, setCategories] = useState<CategoryOut[]>([])
  const [txComposer, setTxComposer] = useState<{ editing?: TransactionOut } | null>(null)

  useEscapeKey(() => {
    if (closingInvoice) setClosingInvoice(null)
    else if (payingInvoice) setPayingInvoice(null)
    else if (newInvoiceOpen) setNewInvoiceOpen(false)
  })

  useEffect(() => {
    api.me().then(setMe).catch(() => navigate('/login'))
  }, [navigate])

  const reload = useCallback(async () => {
    if (!id) return
    const [cs, invs] = await Promise.all([api.listCreditCards(), api.listCardInvoices(id)])
    const open = invs.filter(i => i.status === 'OPEN').sort((a, b) => a.close_date.localeCompare(b.close_date))[0]
    const list = open
      ? await api.listTransactions({ card_id: [id], invoice_id: open.id })
      : { items: [], total: 0 }
    setCards(cs); setInvoices(invs); setTxs(list.items); setTxTotal(list.total); setTxPage(1)
  }, [id])

  useEffect(() => {
    if (!me) return
    // Cadastros dos modais — falha aqui não derruba a página.
    Promise.all([api.listAccounts(), api.listCategories()])
      .then(([accs, cats]) => { setAccounts(accs); setCategories(cats) })
      .catch(() => {})
  }, [me])

  useEffect(() => {
    if (!me || !id) return
    setLoading(true)
    setLoadError('')
    reload()
      .catch(err => setLoadError(err instanceof Error ? err.message : 'Erro ao carregar.'))
      .finally(() => setLoading(false))
  }, [me, id, reload])

  const card = useMemo(() => cards.find(c => c.id === id), [cards, id])
  const openInvoices = useMemo(
    () => invoices.filter(i => i.status === 'OPEN').sort((a, b) => a.close_date.localeCompare(b.close_date)),
    [invoices],
  )
  const openInvoice = openInvoices[0]
  const nextInvoice = openInvoices[1]
  // Faturas futuras (parcelas) não são "anteriores".
  const priorInvoices = useMemo(
    () => invoices.filter(i => i.status !== 'OPEN' || (openInvoice && i.close_date < openInvoice.close_date)),
    [invoices, openInvoice],
  )
  const openTxs = useMemo(() => txs.filter(t => t.invoice_id === openInvoice?.id), [txs, openInvoice])
  const nextTotal = nextInvoice?.tx_total ?? 0
  // Soma no servidor (vale mesmo com lista paginada); fallback pras tx carregadas.
  const openTxSum = useMemo(
    () => openInvoice?.tx_total ?? -openTxs.reduce((acc, t) => acc + t.amount, 0),
    [openInvoice, openTxs],
  )

  /** Recarrega depois de um write que deu certo: erro vai pro toast da
   * página, nunca pro modal (que já fechou ou acharia que o write falhou). */
  async function afterTxWrite() {
    window.dispatchEvent(new Event(CARDS_CHANGED_EVENT))
    try {
      await reload()
    } catch (err) {
      setActionError(`Salvo, mas a página não recarregou: ${err instanceof Error ? err.message : 'erro'}`)
    }
  }

  async function loadMore() {
    if (!id || !openInvoice) return
    setLoadingMore(true)
    try {
      const next = await api.listTransactions({ card_id: [id], invoice_id: openInvoice.id, page: txPage + 1 })
      setTxs(prev => {
        const seen = new Set(prev.map(t => t.id))
        return [...prev, ...next.items.filter(t => !seen.has(t.id))]
      })
      setTxTotal(next.total)
      setTxPage(txPage + 1)
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Erro ao carregar mais.')
    } finally {
      setLoadingMore(false)
    }
  }

  function openComposer(editing?: TransactionOut) {
    attachments.startEditing(editing?.id ?? null)
    setTxComposer({ editing })
  }
  const canWrite = me?.role === 'admin' || me?.role === 'sysadmin'

  if (!me) return null

  return (
    <AppLayout user={me}>
      <div className="space-y-6">
        {loadError ? (
          <Card><div className="text-sm text-red-600 dark:text-red-400 text-center py-6">{loadError}</div></Card>
        ) : loading || !card ? (
          <Card><div className="text-sm text-gray-400 dark:text-gray-600 text-center py-12">Carregando…</div></Card>
        ) : (
          <>
            <Card padding="p-6">
              <div className="flex items-start gap-4">
                <FILogo slug={card.fi_logo_slug} shortName={card.financial_institution_name} size="lg" />
                <div className="flex-1">
                  <div className="flex items-center gap-2">
                    <h1 className="text-2xl font-semibold text-gray-900 dark:text-white">{card.name}</h1>
                    {card.brand && (
                      <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-md text-[10px] font-medium uppercase tracking-wider bg-amber-500/10 text-amber-600 dark:text-amber-400">
                        <CreditCardIcon className="w-3 h-3" /> {card.brand}
                      </span>
                    )}
                  </div>
                  <div className="text-[13px] text-gray-500 mt-0.5 flex items-center gap-2">
                    <span>{card.financial_institution_name}</span>
                    {card.last4 && <><span>·</span><span>···· {card.last4}</span></>}
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <ImportButton label="Importar fatura" importing={imports.importing}
                    inputRef={imports.inputRef} onPick={imports.onPick} />
                  <button onClick={() => openComposer()} className="h-8 px-3 inline-flex items-center gap-1.5 rounded-lg text-[12px] bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700 transition-colors">
                    <Plus className="w-3.5 h-3.5" /> Lançamento
                  </button>
                  {canWrite && (
                    <button onClick={() => setNewInvoiceOpen(true)} className="h-8 px-3 inline-flex items-center gap-1.5 rounded-lg text-[12px] bg-indigo-500 hover:bg-indigo-400 text-white transition-colors">
                      <Plus className="w-3.5 h-3.5" /> Nova fatura
                    </button>
                  )}
                </div>
              </div>
            </Card>

            <div className="grid grid-cols-12 gap-6">
              <Card className="col-span-12 lg:col-span-8">
                <div className="flex items-baseline justify-between">
                  <div>
                    <div className="text-[11px] uppercase tracking-wider text-gray-500">
                      Fatura aberta{openInvoice && <> · vence {fmtDate(openInvoice.due_date)}</>}
                    </div>
                    <div className="text-3xl font-semibold tnum money text-amber-500 dark:text-amber-400 mt-1">
                      {fmtMoney(card.open_invoice_total, card.currency)}
                    </div>
                    <div className="mt-1 text-[11px] text-gray-500">
                      Fechamento dia <span className="tnum text-gray-700 dark:text-gray-300">{card.close_day}</span> · vencimento dia <span className="tnum text-gray-700 dark:text-gray-300">{card.due_day}</span>
                    </div>
                  </div>
                  {card.credit_limit != null && (
                    <div className="text-right">
                      <div className="text-[11px] uppercase tracking-wider text-gray-500">Limite utilizado</div>
                      <div className="text-base font-medium tnum text-gray-900 dark:text-white">{card.limit_used_pct != null ? fmtPct(card.limit_used_pct, 1) : '—'}</div>
                      <div className="text-[11px] text-gray-500 tnum money">{fmtMoney(card.open_invoice_total, card.currency)} / {fmtMoney(card.credit_limit, card.currency)}</div>
                    </div>
                  )}
                </div>
                {card.credit_limit != null && (
                  <div className="mt-3"><HBar value={card.open_invoice_total} max={card.credit_limit} /></div>
                )}
                <div className="mt-5 grid grid-cols-2 md:grid-cols-4 gap-3">
                  <KpiTile label="Lançamentos" value={String(openInvoice ? txTotal : 0)} />
                  <KpiTile label="IOF · cartão" value={openInvoice?.iof_total != null ? fmtMoney(openInvoice.iof_total, card.currency) : '—'} />
                  <KpiTile label="Compras parceladas" value={String(openTxs.filter(t => t.installment_total).length)} />
                  <KpiTile label="Próx. fatura · estimada" value={nextInvoice ? fmtMoney(nextTotal, card.currency) : '—'} />
                </div>
              </Card>

              <Card className="col-span-12 lg:col-span-4">
                <SectionTitle>Faturas anteriores</SectionTitle>
                {priorInvoices.length === 0 ? (
                  <div className="text-[12px] text-gray-400 dark:text-gray-600 py-4">Nenhuma fatura anterior.</div>
                ) : (
                  <div className="space-y-1.5">
                    {priorInvoices.map(inv => (
                      <div key={inv.id} className="flex items-center gap-3 px-2 py-1.5 -mx-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800/40">
                        <div className="flex-1 text-[12px]">
                          <div className="font-medium text-gray-900 dark:text-white">Fecho {fmtDate(inv.close_date)}</div>
                          <div className="text-[10px] text-gray-500">{STATUS_META[inv.status].label}{inv.paid_at && ` em ${fmtDate(inv.paid_at)}`}</div>
                          {invoiceDiverges(inv) && (
                            <div className="text-[10px] text-amber-600 dark:text-amber-400" data-testid={`invoice-divergence-${inv.id}`}
                              title="Lançamento entrou ou mudou depois do fechamento — confira antes de pagar">
                              soma dos lançamentos {fmtMoney(inv.tx_total!, inv.currency)} ≠ total congelado
                            </div>
                          )}
                        </div>
                        <div className="text-[12px] tnum money text-gray-900 dark:text-white">{inv.total_amount != null ? fmtMoney(inv.total_amount, inv.currency) : '—'}</div>
                        {inv.status === 'PAID' && <Check className="w-3.5 h-3.5 text-emerald-500 dark:text-emerald-400" />}
                        {inv.status === 'CLOSED' && (
                          <button onClick={() => setPayingInvoice(inv)}
                            className="h-6 px-2 inline-flex items-center gap-1 rounded-md text-[10px] bg-indigo-500/10 text-indigo-600 dark:text-indigo-300 hover:bg-indigo-500/20">
                            <Wallet className="w-3 h-3" /> Pagar
                          </button>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </Card>
            </div>

            <Card>
              <SectionTitle action={openInvoice && canWrite ? (
                <button onClick={() => setClosingInvoice(openInvoice)} className="h-7 px-2 inline-flex items-center gap-1 rounded-md text-[11px] bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700">
                  <Pencil className="w-3 h-3" /> Fechar fatura
                </button>
              ) : undefined}>
                Lançamentos da fatura aberta
              </SectionTitle>
              {openTxs.length === 0 ? (
                <div className="text-[12px] text-gray-400 dark:text-gray-600 text-center py-8">
                  Nenhum lançamento na fatura aberta.
                </div>
              ) : (
                <table className="w-full text-[12px]">
                  <tbody>
                    {openTxs.map(t => (
                      <tr key={t.id} onClick={() => openComposer(t)}
                        className="border-t border-gray-100 dark:border-gray-800 hover:bg-gray-50 dark:hover:bg-gray-800/30 cursor-pointer">
                        <td className="px-2 py-2 tnum text-gray-400 w-16">{fmtDate(t.event_date)}</td>
                        <td className="px-2 text-gray-900 dark:text-white">
                          {t.description}
                          {t.installment_total && <span className="ml-1.5 text-[10px] text-gray-500">parc. {t.installment_number}/{t.installment_total}</span>}
                          {t.is_projected && <span className="ml-1.5 text-[9px] uppercase tracking-wider px-1 rounded bg-amber-500/10 text-amber-600 dark:text-amber-300" title={t.notes ?? undefined} data-testid={`projected-${t.id}`}>prevista</span>}
                          <span className="ml-1 align-middle"><SourceFileClip attachmentId={t.source_attachment_id} filename={t.source_attachment_filename} onError={setActionError} /></span>
                        </td>
                        <td className="px-2 text-[11px] text-gray-500">{t.category_name ?? <span className="italic">Sem categoria</span>}</td>
                        <td className={`px-2 text-right tnum money font-medium ${t.amount > 0 ? 'text-emerald-500 dark:text-emerald-400' : 'text-gray-900 dark:text-white'}`}>
                          {fmtMoney(t.amount, t.currency)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
              <LoadMore shown={openTxs.length} total={openInvoice ? txTotal : 0} loading={loadingMore} onLoadMore={loadMore} />
            </Card>

            <ImportHistory title="Faturas importadas" history={imports.history}
              onReview={imports.setReviewing} onError={setActionError} />

            {cards.length > 1 && (
              <Card padding="p-4" className="bg-gray-50 dark:bg-gray-900/40">
                <div className="text-[10px] uppercase tracking-wider text-gray-500 mb-2">Outros cartões</div>
                <div className="flex flex-wrap gap-2">
                  {cards.map(c => (
                    <Link key={c.id} to={`/credit-cards/${c.id}`}
                      className={`text-[11px] px-2 py-1 rounded-md border transition-colors ${
                        c.id === card.id
                          ? 'border-indigo-500 bg-indigo-500/15 text-indigo-600 dark:text-indigo-300'
                          : 'border-gray-200 dark:border-gray-800 text-gray-500 hover:text-gray-700 dark:hover:text-gray-300 hover:border-gray-400 dark:hover:border-gray-700'}`}>
                      {c.name}
                    </Link>
                  ))}
                </div>
              </Card>
            )}
          </>
        )}

        {actionError && (
          <div className="fixed bottom-4 right-4 z-[70] max-w-sm bg-red-600 text-white text-[12px] rounded-lg shadow-lg px-4 py-3">
            {actionError}
            <button onClick={() => setActionError('')} className="ml-3 underline">fechar</button>
          </div>
        )}
      </div>

      {imports.reviewing && (
        <BankImportReviewModal
          job={imports.reviewing} accounts={accounts} categories={categories}
          onApplied={result => {
            imports.setReviewing(null)
            setNotice(summarizeResult(result))
            void imports.reloadHistory()
            void afterTxWrite()
          }}
          onClose={() => { imports.setReviewing(null); void imports.reloadHistory() }}
        />
      )}

      {notice && (
        <div className="fixed bottom-4 left-4 z-[70] max-w-sm bg-emerald-600 text-white text-[12px] rounded-lg shadow-lg px-4 py-3" role="status">
          {notice}
          <button onClick={() => setNotice('')} className="ml-3 underline">fechar</button>
        </div>
      )}

      {newInvoiceOpen && card && (
        <InvoiceModal
          onSave={async data => {
            await api.createInvoice(card.id, data)
            await afterTxWrite()
          }}
          onClose={() => setNewInvoiceOpen(false)}
        />
      )}

      {payingInvoice && (
        <PayInvoiceModal
          invoice={payingInvoice}
          accounts={accounts}
          categories={categories}
          onConfirm={async data => {
            await api.payInvoice(payingInvoice.id, data)
            setPayingInvoice(null)
            void afterTxWrite()
          }}
          onClose={() => setPayingInvoice(null)}
        />
      )}

      {txComposer && card && (
        <CardTxComposer
          cards={cards} categories={categories} invoices={invoices}
          initial={txComposer.editing} defaultCardId={card.id}
          onCreate={async (data: TransactionCreatePayload) => { const r = await api.createTransaction(data); await afterTxWrite(); return r }}
          onUpdate={async (txId: string, data: TransactionUpdatePayload) => { const r = await api.updateTransaction(txId, data); await afterTxWrite(); return r }}
          onClose={() => setTxComposer(null)}
          persistedAttachments={txComposer.editing ? attachments.persisted : undefined}
          onUploadDrafts={attachments.uploadDrafts}
          onRemovePersistedAttachment={attachments.removePersisted}
        />
      )}

      {closingInvoice && (
        <CloseInvoiceModal
          invoice={closingInvoice}
          txSum={closingInvoice.id === openInvoice?.id && (openInvoice.tx_total != null || openTxs.length) ? openTxSum : null}
          onConfirm={async total => {
            try {
              await api.closeInvoice(closingInvoice.id, total)
            } catch (err) {
              setActionError(err instanceof Error ? err.message : 'Erro ao fechar fatura.')
              return
            }
            setClosingInvoice(null)
            await afterTxWrite()
          }}
          onClose={() => setClosingInvoice(null)}
        />
      )}
    </AppLayout>
  )
}

function InvoiceModal({ onSave, onClose }: {
  onSave: (data: { close_date: string; due_date: string; total_amount?: number | null }) => Promise<void>
  onClose: () => void
}) {
  const [closeDate, setCloseDate] = useState('')
  const [dueDate, setDueDate] = useState('')
  const [total, setTotal] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    setSaving(true)
    try {
      await onSave({ close_date: closeDate, due_date: dueDate, total_amount: total !== '' ? parseDecimal(total) : null })
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Erro ao salvar.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="w-full max-w-sm bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-800 shadow-xl p-6">
        <h2 className="text-base font-semibold text-gray-900 dark:text-white mb-5">Nova fatura</h2>
        <form onSubmit={handleSubmit} className="space-y-3">
          <Field label="Fechamento">
            <input type="date" value={closeDate} onChange={e => setCloseDate(e.target.value)} required className={INPUT_CLS} />
          </Field>
          <Field label="Vencimento">
            <input type="date" value={dueDate} onChange={e => setDueDate(e.target.value)} required className={INPUT_CLS} />
          </Field>
          <Field label="Total (opcional enquanto aberta)">
            <input type="text" value={total} onChange={e => setTotal(e.target.value)} placeholder="0,00" className={INPUT_CLS} />
          </Field>
          {error && <p className="text-[12px] text-red-500 dark:text-red-400">{error}</p>}
          <div className="flex justify-end gap-2 pt-2">
            <button type="button" onClick={onClose} className="h-9 px-4 inline-flex items-center rounded-lg text-[12px] text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors">Cancelar</button>
            <button type="submit" disabled={saving} className="h-9 px-4 inline-flex items-center rounded-lg bg-indigo-500 hover:bg-indigo-400 disabled:opacity-60 text-white text-[12px] font-medium transition-colors">
              {saving ? 'Salvando…' : 'Criar'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

function CloseInvoiceModal({ invoice, txSum, onConfirm, onClose }: {
  invoice: InvoiceOut
  /** Soma das tx da fatura — default do total (spec 70). */
  txSum: number | null
  onConfirm: (total: number) => Promise<void>
  onClose: () => void
}) {
  const [total, setTotal] = useState(
    (invoice.total_amount ?? (txSum != null ? Math.round(txSum * 100) / 100 : null))?.toString().replace('.', ',') ?? '',
  )
  const [saving, setSaving] = useState(false)

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/40">
      <div className="w-full max-w-sm bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-700 shadow-xl p-6">
        <h2 className="text-base font-semibold text-gray-900 dark:text-white mb-2">Fechar fatura?</h2>
        <p className="text-sm text-gray-500 dark:text-gray-400 mb-4">
          Fechamento {fmtDate(invoice.close_date)} · vencimento {fmtDate(invoice.due_date)}. O total é congelado.
        </p>
        <Field label="Total da fatura">
          <input type="text" value={total} onChange={e => setTotal(e.target.value)} placeholder="0,00" autoFocus className={INPUT_CLS} />
        </Field>
        <div className="flex justify-end gap-3 mt-5">
          <button onClick={onClose} className="px-4 py-2 rounded-lg text-sm text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors">Cancelar</button>
          <button
            disabled={saving || total === '' || parseDecimal(total) == null}
            onClick={async () => {
              const v = parseDecimal(total)
              if (v == null) return
              setSaving(true)
              try { await onConfirm(v) } finally { setSaving(false) }
            }}
            className="px-4 py-2 rounded-lg bg-indigo-500 hover:bg-indigo-400 disabled:opacity-60 text-white text-sm font-medium transition-colors"
          >
            {saving ? 'Fechando…' : 'Fechar fatura'}
          </button>
        </div>
      </div>
    </div>
  )
}

function PayInvoiceModal({ invoice, accounts, categories, onConfirm, onClose }: {
  invoice: InvoiceOut
  accounts: AccountOut[]
  categories: CategoryOut[]
  onConfirm: (data: InvoicePayPayload) => Promise<void>
  onClose: () => void
}) {
  const checkings = accounts.filter(a => a.account_type === 'checking' && a.is_active)
  const sameCcy = checkings.filter(a => a.currency === invoice.currency)
  const [accIdState, setAccId] = useState('')
  const accId = accIdState || (sameCcy[0] ?? checkings[0])?.id || ''
  const [paidOn, setPaidOn] = useState(todayISO())
  const diverged = invoiceDiverges(invoice)
  // O valor é na moeda da CONTA: só pré-preenche com o total da fatura
  // quando as moedas batem (e o total congelado ainda bate com as tx).
  const defaultAmount = (accountId: string) => {
    const a = accounts.find(x => x.id === accountId)
    return a && a.currency === invoice.currency && invoice.total_amount != null && !diverged
      ? String(invoice.total_amount).replace('.', ',')
      : ''
  }
  const [amount, setAmount] = useState(() => defaultAmount(accId))
  const [catId, setCatId] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const acc = accounts.find(a => a.id === accId)
  const amountN = parseDecimal(amount)
  const valid = !!acc && amountN != null && amountN > 0

  async function submit() {
    setSaving(true)
    setError('')
    try {
      await onConfirm({ checking_account_id: accId, paid_on: paidOn, amount: amountN, category_id: catId || null })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Erro ao pagar fatura.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/40">
      <div role="dialog" aria-label="Pagar fatura" className="w-full max-w-sm bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-700 shadow-xl p-6">
        <h2 className="text-base font-semibold text-gray-900 dark:text-white mb-2">Pagar fatura</h2>
        <p className="text-sm text-gray-500 dark:text-gray-400 mb-4">
          Fechamento {fmtDate(invoice.close_date)} · vencimento {fmtDate(invoice.due_date)}. Cria a saída na conta — é transferência, não despesa.
        </p>
        <div className="space-y-3">
          <Field label="Conta corrente">
            <select value={accId} onChange={e => { setAccId(e.target.value); setAmount(defaultAmount(e.target.value)) }} className={INPUT_CLS} aria-label="Conta corrente">
              {checkings.map(a => <option key={a.id} value={a.id}>{a.name} · {a.currency}</option>)}
            </select>
          </Field>
          <Field label="Data do pagamento">
            <input type="date" value={paidOn} onChange={e => setPaidOn(e.target.value)} className={INPUT_CLS} aria-label="Data do pagamento" />
          </Field>
          <Field label={`Valor pago · ${acc?.currency ?? invoice.currency}`}>
            <input type="text" value={amount} onChange={e => setAmount(e.target.value)} placeholder="0,00" className={INPUT_CLS} aria-label="Valor pago" />
          </Field>
          {acc && acc.currency !== invoice.currency && (
            <p className="text-[11px] text-amber-600 dark:text-amber-400">
              Fatura em {invoice.currency}, conta em {acc.currency} — informe o valor debitado na conta.
            </p>
          )}
          {diverged && (
            <p className="text-[11px] text-amber-600 dark:text-amber-400" data-testid="pay-divergence">
              Total congelado {fmtMoney(invoice.total_amount!, invoice.currency)} × soma dos lançamentos {fmtMoney(invoice.tx_total!, invoice.currency)} — informe o valor pago.
            </p>
          )}
          <Field label="Categoria (opcional)">
            <CategorySelect categories={categories} value={catId} onChange={setCatId} filterKind="TRANSFER" />
          </Field>
        </div>
        {error && <p className="text-[12px] text-red-500 dark:text-red-400 mt-3">{error}</p>}
        <div className="flex justify-end gap-3 mt-5">
          <button onClick={onClose} className="px-4 py-2 rounded-lg text-sm text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors">Cancelar</button>
          <button disabled={!valid || saving} onClick={submit}
            className="px-4 py-2 rounded-lg bg-indigo-500 hover:bg-indigo-400 disabled:opacity-60 text-white text-sm font-medium transition-colors">
            {saving ? 'Pagando…' : 'Pagar fatura'}
          </button>
        </div>
      </div>
    </div>
  )
}
