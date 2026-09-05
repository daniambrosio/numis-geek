/* Spec 69 — Detalhe do cartão (/credit-cards/:id), fiel ao proto CartaoDetail
 * (index.html:3620-3721): hero com fatura aberta + barra de limite, KPIs,
 * card lateral "Faturas anteriores", navegação entre cartões.
 * KPIs "Lançamentos" e "Compras parceladas" ficam — até a spec 70; botão
 * "Importar fatura" disabled até a spec 71. "Fechar fatura" e "Nova fatura"
 * são deltas declarados na spec (proto não modela o ciclo).
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { Check, CreditCard as CreditCardIcon, FileText, Pencil, Plus } from 'lucide-react'
import { api, type CreditCardOut, type InvoiceOut, type UserOut } from '../lib/api'
import AppLayout from '../components/AppLayout'
import { Card, SectionTitle, FILogo, Field, INPUT_CLS } from '../components/ui'
import { parseDecimal } from '../lib/parseDecimal'
import { useEscapeKey } from '../lib/useEscapeKey'
import { fmtMoney, fmtPct } from './CreditCards'
import KpiTile from '../components/KpiTile'

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
  const [actionError, setActionError] = useState('')

  useEscapeKey(() => {
    if (closingInvoice) setClosingInvoice(null)
    else if (newInvoiceOpen) setNewInvoiceOpen(false)
  })

  useEffect(() => {
    api.me().then(setMe).catch(() => navigate('/login'))
  }, [navigate])

  const reload = useCallback(() => {
    if (!id) return Promise.resolve()
    return Promise.all([api.listCreditCards(), api.listCardInvoices(id)])
      .then(([cs, invs]) => { setCards(cs); setInvoices(invs) })
  }, [id])

  useEffect(() => {
    if (!me || !id) return
    setLoading(true)
    setLoadError('')
    reload()
      .catch(err => setLoadError(err instanceof Error ? err.message : 'Erro ao carregar.'))
      .finally(() => setLoading(false))
  }, [me, id, reload])

  const card = useMemo(() => cards.find(c => c.id === id), [cards, id])
  const openInvoice = useMemo(() => invoices.find(i => i.status === 'OPEN'), [invoices])
  const priorInvoices = useMemo(() => invoices.filter(i => i.id !== openInvoice?.id), [invoices, openInvoice])
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
                  <button disabled title="Chega com a spec 71 (import de fatura)" className="h-8 px-3 inline-flex items-center gap-1.5 rounded-lg text-[12px] bg-gray-100 dark:bg-gray-800 text-gray-400 dark:text-gray-600 cursor-not-allowed">
                    <FileText className="w-3.5 h-3.5" /> Importar fatura
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
                  <KpiTile label="Lançamentos" value="—" />
                  <KpiTile label="IOF · cartão" value={openInvoice?.iof_total != null ? fmtMoney(openInvoice.iof_total, card.currency) : '—'} />
                  <KpiTile label="Compras parceladas" value="—" />
                  <KpiTile label="Próx. fatura · estimada" value="—" />
                </div>
                <div className="mt-2 text-[10px] text-gray-400 dark:text-gray-600">Lançamentos e parcelas chegam com as Movimentações (spec 70).</div>
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
                        </div>
                        <div className="text-[12px] tnum money text-gray-900 dark:text-white">{inv.total_amount != null ? fmtMoney(inv.total_amount, inv.currency) : '—'}</div>
                        {inv.status === 'PAID' && <Check className="w-3.5 h-3.5 text-emerald-500 dark:text-emerald-400" />}
                        {inv.status === 'CLOSED' && canWrite && (
                          <span className="text-[10px] text-blue-500">aguarda pgto</span>
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
              <div className="text-[12px] text-gray-400 dark:text-gray-600 text-center py-8">
                As transações do cartão chegam com as Movimentações (specs 70/71 — composer e import de fatura).
              </div>
            </Card>

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

      {newInvoiceOpen && card && (
        <InvoiceModal
          onSave={async data => { await api.createInvoice(card.id, data); await reload() }}
          onClose={() => setNewInvoiceOpen(false)}
        />
      )}

      {closingInvoice && (
        <CloseInvoiceModal
          invoice={closingInvoice}
          onConfirm={async total => {
            try {
              await api.closeInvoice(closingInvoice.id, total)
              setClosingInvoice(null)
              await reload()
            } catch (err) {
              setActionError(err instanceof Error ? err.message : 'Erro ao fechar fatura.')
            }
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

function CloseInvoiceModal({ invoice, onConfirm, onClose }: {
  invoice: InvoiceOut
  onConfirm: (total: number) => Promise<void>
  onClose: () => void
}) {
  const [total, setTotal] = useState(invoice.total_amount?.toString() ?? '')
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
