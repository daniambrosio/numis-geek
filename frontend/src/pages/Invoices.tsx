/* Spec 69 — Faturas (/invoices), fiel ao proto FaturasPage (index.html:
 * 6732-6846): 3 KPIs (Em aberto / Pagas YTD / Fatura média), filtros
 * Status + Cartão, tabela clicável → detalhe do cartão.
 * Delta declarado: status tem 3 valores (Aberta/Fechada/Paga) — o proto
 * só tinha isPaid; "Abertas" no filtro = OPEN + CLOSED (não pagas).
 */
import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Check, ChevronRight, FileText } from 'lucide-react'
import { api, type CreditCardOut, type InvoiceOut, type UserOut } from '../lib/api'
import AppLayout from '../components/AppLayout'
import { Card, PageHeader, SectionTitle, FILogo, FilterGroup, GroupingToggle, MultiChips } from '../components/ui'
import { fmtMoney } from './CreditCards'

function fmtDate(iso: string) {
  const [y, m, d] = iso.split('-')
  return `${d}/${m}/${y.slice(2)}`
}

export type StatusFilter = 'all' | 'open' | 'paid'

/** Filtro de status: "Abertas" = não pagas (OPEN + CLOSED). */
export function filterInvoices(invoices: InvoiceOut[], status: StatusFilter, cardIds: string[]): InvoiceOut[] {
  let xs = invoices
  if (cardIds.length) xs = xs.filter(i => cardIds.includes(i.credit_card_account_id))
  if (status === 'open') xs = xs.filter(i => i.status !== 'PAID')
  if (status === 'paid') xs = xs.filter(i => i.status === 'PAID')
  return [...xs].sort((a, b) => b.due_date.localeCompare(a.due_date))
}

export function invoiceKpis(invoices: InvoiceOut[], year: number) {
  const open = invoices.filter(i => i.status !== 'PAID')
  const paidYTD = invoices.filter(i => i.status === 'PAID' && i.paid_at?.startsWith(String(year)))
  const withTotal = invoices.filter(i => i.total_amount != null)
  return {
    totalOpen: open.reduce((s, i) => s + (i.total_amount ?? 0), 0),
    openCount: open.length,
    totalPaidYTD: paidYTD.reduce((s, i) => s + (i.total_amount ?? 0), 0),
    paidCount: paidYTD.length,
    avgInvoice: withTotal.length ? withTotal.reduce((s, i) => s + (i.total_amount ?? 0), 0) / withTotal.length : 0,
  }
}

const STATUS_BADGE: Record<InvoiceOut['status'], { label: string; cls: string; icon?: boolean }> = {
  OPEN: { label: 'Aberta', cls: 'bg-amber-500/15 text-amber-600 dark:text-amber-400' },
  CLOSED: { label: 'Fechada', cls: 'bg-blue-500/15 text-blue-600 dark:text-blue-400' },
  PAID: { label: 'Paga', cls: 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400', icon: true },
}

export default function Invoices() {
  const navigate = useNavigate()
  const [me, setMe] = useState<UserOut | null>(null)
  const [invoices, setInvoices] = useState<InvoiceOut[]>([])
  const [cards, setCards] = useState<CreditCardOut[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all')
  const [cardFilter, setCardFilter] = useState<string[]>([])

  useEffect(() => {
    api.me().then(setMe).catch(() => navigate('/login'))
  }, [navigate])

  useEffect(() => {
    if (!me) return
    setLoading(true)
    setLoadError('')
    Promise.all([api.listInvoices(), api.listCreditCards()])
      .then(([invs, cs]) => { setInvoices(invs); setCards(cs) })
      .catch(err => setLoadError(err instanceof Error ? err.message : 'Erro ao carregar.'))
      .finally(() => setLoading(false))
  }, [me])

  const cardById = useMemo(() => new Map(cards.map(c => [c.id, c])), [cards])
  const filtered = useMemo(() => filterInvoices(invoices, statusFilter, cardFilter), [invoices, statusFilter, cardFilter])
  const kpis = useMemo(() => invoiceKpis(invoices, new Date().getFullYear()), [invoices])
  const cardOpts = useMemo(() => cards.map(c => ({ id: c.id, label: c.name })), [cards])

  if (!me) return null

  return (
    <AppLayout user={me}>
      <div className="space-y-6">
        <PageHeader
          title="Faturas"
          count={invoices.length}
          countLabel={`faturas · ${cards.length} ${cards.length === 1 ? 'cartão' : 'cartões'}`}
          action={
            <button disabled title="Chega com a spec 71 (import de fatura)" className="h-8 px-3 inline-flex items-center gap-1.5 rounded-lg text-[12px] bg-gray-100 dark:bg-gray-800 text-gray-400 dark:text-gray-600 cursor-not-allowed">
              <FileText className="w-3.5 h-3.5" /> Importar fatura
            </button>
          }
        />

        <div className="grid grid-cols-12 gap-4">
          <Card className="col-span-12 lg:col-span-4">
            <SectionTitle>Em aberto</SectionTitle>
            <div className="text-3xl font-semibold tnum money text-amber-500 dark:text-amber-400">{fmtMoney(kpis.totalOpen, 'BRL')}</div>
            <div className="text-[11px] text-gray-500 mt-1"><span className="tnum">{kpis.openCount}</span> faturas abertas</div>
          </Card>
          <Card className="col-span-12 lg:col-span-4">
            <SectionTitle>Pagas · YTD</SectionTitle>
            <div className="text-3xl font-semibold tnum money text-emerald-600 dark:text-emerald-400">{fmtMoney(kpis.totalPaidYTD, 'BRL')}</div>
            <div className="text-[11px] text-gray-500 mt-1"><span className="tnum">{kpis.paidCount}</span> faturas no ano</div>
          </Card>
          <Card className="col-span-12 lg:col-span-4">
            <SectionTitle>Fatura média</SectionTitle>
            <div className="text-3xl font-semibold tnum money text-gray-900 dark:text-white">{fmtMoney(kpis.avgInvoice, 'BRL')}</div>
            <div className="text-[11px] text-gray-500 mt-1">por cartão / mês</div>
          </Card>
        </div>

        <Card padding="p-3" className="space-y-3">
          <div className="flex items-center gap-3 flex-wrap">
            <span className="text-[10px] uppercase tracking-wider text-gray-500 font-medium min-w-[90px]">Status</span>
            <GroupingToggle
              value={statusFilter}
              onChange={v => setStatusFilter(v as StatusFilter)}
              options={[
                { id: 'all', label: 'Todas' },
                { id: 'open', label: 'Abertas' },
                { id: 'paid', label: 'Pagas' },
              ]}
            />
          </div>
          {cardOpts.length > 0 && (
            <div className="space-y-2 pt-3 border-t border-gray-200 dark:border-gray-800">
              <FilterGroup label="Cartão">
                <MultiChips options={cardOpts} selected={cardFilter} onChange={setCardFilter} />
              </FilterGroup>
            </div>
          )}
        </Card>

        <Card padding="p-3">
          {loadError ? (
            <div className="text-sm text-red-600 dark:text-red-400 text-center py-6">{loadError}</div>
          ) : loading ? (
            <div className="text-sm text-gray-400 dark:text-gray-600 text-center py-8">Carregando…</div>
          ) : filtered.length === 0 ? (
            <div className="text-[12px] text-gray-400 dark:text-gray-600 text-center py-8">
              {invoices.length === 0 ? 'Nenhuma fatura ainda — crie no detalhe do cartão ou importe (spec 71).' : 'Nada com esses filtros.'}
            </div>
          ) : (
            <div className="overflow-x-auto -mx-1">
              <table className="w-full text-[12px]">
                <thead>
                  <tr className="text-[10px] uppercase tracking-wider text-gray-500">
                    <th className="text-left font-medium px-2 py-2">Cartão</th>
                    <th className="text-left font-medium px-2 py-2">Fechamento</th>
                    <th className="text-left font-medium px-2 py-2">Vencimento</th>
                    <th className="text-right font-medium px-2 py-2">Total</th>
                    <th className="text-center font-medium px-2 py-2">Status</th>
                    <th className="text-left font-medium px-2 py-2">Pago em</th>
                    <th className="px-2" />
                  </tr>
                </thead>
                <tbody>
                  {filtered.map(inv => {
                    const card = cardById.get(inv.credit_card_account_id)
                    const badge = STATUS_BADGE[inv.status]
                    return (
                      <tr
                        key={inv.id}
                        onClick={() => navigate(`/credit-cards/${inv.credit_card_account_id}`)}
                        className="border-t border-gray-100 dark:border-gray-800 hover:bg-gray-50 dark:hover:bg-gray-800/30 transition-colors cursor-pointer"
                      >
                        <td className="px-2 py-2">
                          <div className="flex items-center gap-2">
                            <FILogo slug={card?.fi_logo_slug ?? null} shortName={card?.financial_institution_name ?? '··'} size="sm" />
                            <div className="min-w-0">
                              <div className="text-[12px] font-medium truncate text-gray-900 dark:text-white">{inv.credit_card_name}</div>
                              {card?.last4 && <div className="text-[10px] text-gray-500">···· {card.last4}</div>}
                            </div>
                          </div>
                        </td>
                        <td className="px-2 tnum text-gray-400">{fmtDate(inv.close_date)}</td>
                        <td className="px-2 tnum text-gray-700 dark:text-gray-300">{fmtDate(inv.due_date)}</td>
                        <td className={`px-2 text-right tnum money font-medium ${inv.status !== 'PAID' ? 'text-amber-500 dark:text-amber-400' : 'text-gray-900 dark:text-white'}`}>
                          {inv.total_amount != null ? fmtMoney(inv.total_amount, inv.currency) : '—'}
                        </td>
                        <td className="px-2 text-center">
                          <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] uppercase tracking-wider ${badge.cls}`}>
                            {badge.icon && <Check className="w-3 h-3" />}{badge.label}
                          </span>
                        </td>
                        <td className="px-2 tnum text-[11px] text-gray-500">{inv.paid_at ? fmtDate(inv.paid_at) : '—'}</td>
                        <td className="px-2 text-gray-500"><ChevronRight className="w-4 h-4" /></td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>
    </AppLayout>
  )
}
