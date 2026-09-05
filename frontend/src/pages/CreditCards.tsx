/* Spec 69 — Cartões de crédito (/credit-cards), fiel ao proto CartoesList
 * (index.html:3230-3257): header com % do limite total, 3 KpiTiles
 * (Total em fatura aberta / Limite total / Disponível), lista de CardRow.
 * Extras além do proto (declarados na spec): modal de criar/editar cartão
 * (abre via ?compose=card do menu Novo) e desativar.
 */
import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { CreditCard as CreditCardIcon, Plus } from 'lucide-react'
import { api, type CreditCardOut, type CreditCardPayload, type FinancialInstitutionOut, type UserOut } from '../lib/api'
import AppLayout from '../components/AppLayout'
import { Card, SectionTitle, FILogo, Field, INPUT_CLS } from '../components/ui'
import KpiTile from '../components/KpiTile'
import { parseDecimal } from '../lib/parseDecimal'
import { useEscapeKey } from '../lib/useEscapeKey'

export function fmtMoney(n: number, ccy: string) {
  return n.toLocaleString('pt-BR', { style: 'currency', currency: ccy })
}

export function fmtPct(v: number, digits = 0) {
  return `${(v * 100).toFixed(digits)}%`
}

/** KPIs do topo — soma em BRL nominal (conversão PTAX chega com dual-currency das próximas specs). */
export function cardKpis(cards: CreditCardOut[]) {
  const total = cards.reduce((s, c) => s + c.open_invoice_total, 0)
  const totalLimit = cards.reduce((s, c) => s + (c.credit_limit ?? 0), 0)
  return { total, totalLimit, available: totalLimit - total, usedPct: totalLimit > 0 ? total / totalLimit : 0 }
}

interface ModalProps {
  initial?: CreditCardOut
  institutions: FinancialInstitutionOut[]
  onSave: (data: CreditCardPayload) => Promise<void>
  onClose: () => void
}

function CardModal({ initial, institutions, onSave, onClose }: ModalProps) {
  const [name, setName] = useState(initial?.name ?? '')
  const [fiId, setFiId] = useState(initial?.financial_institution_id ?? (institutions[0]?.id ?? ''))
  const [currency, setCurrency] = useState<'BRL' | 'USD'>(initial?.currency ?? 'BRL')
  const [brand, setBrand] = useState(initial?.brand ?? '')
  const [last4, setLast4] = useState(initial?.last4 ?? '')
  const [creditLimit, setCreditLimit] = useState(initial?.credit_limit?.toString() ?? '')
  const [closeDay, setCloseDay] = useState(initial?.close_day?.toString() ?? '5')
  const [dueDay, setDueDay] = useState(initial?.due_day?.toString() ?? '15')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    setSaving(true)
    try {
      await onSave({
        name,
        financial_institution_id: fiId,
        currency,
        brand: brand.trim() || null,
        last4: last4.trim() || null,
        credit_limit: creditLimit !== '' ? parseDecimal(creditLimit) : null,
        close_day: parseInt(closeDay, 10),
        due_day: parseInt(dueDay, 10),
      })
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Erro ao salvar.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="w-full max-w-md bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-800 shadow-xl p-6">
        <h2 className="text-base font-semibold text-gray-900 dark:text-white mb-5">
          {initial ? 'Editar cartão' : 'Novo cartão de crédito'}
        </h2>
        <form onSubmit={handleSubmit} className="space-y-3">
          <Field label="Nome">
            <input type="text" value={name} onChange={e => setName(e.target.value)} required placeholder="Ex: Itaú Visa Infinite" className={INPUT_CLS} />
          </Field>
          <Field label="Instituição">
            <select value={fiId} onChange={e => setFiId(e.target.value)} required className={INPUT_CLS}>
              {institutions.map(fi => <option key={fi.id} value={fi.id}>{fi.short_name}</option>)}
            </select>
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Bandeira">
              <input type="text" value={brand} onChange={e => setBrand(e.target.value)} placeholder="Visa, Mastercard…" className={INPUT_CLS} />
            </Field>
            <Field label="Final (4 dígitos)">
              <input type="text" value={last4} onChange={e => setLast4(e.target.value)} maxLength={4} placeholder="4421" className={INPUT_CLS} />
            </Field>
          </div>
          <div className="grid grid-cols-3 gap-3">
            <Field label="Moeda">
              <select value={currency} onChange={e => setCurrency(e.target.value as 'BRL' | 'USD')} className={INPUT_CLS}>
                <option value="BRL">BRL</option>
                <option value="USD">USD</option>
              </select>
            </Field>
            <Field label="Fecha dia">
              <input type="number" min={1} max={28} value={closeDay} onChange={e => setCloseDay(e.target.value)} required className={INPUT_CLS} />
            </Field>
            <Field label="Vence dia">
              <input type="number" min={1} max={28} value={dueDay} onChange={e => setDueDay(e.target.value)} required className={INPUT_CLS} />
            </Field>
          </div>
          <Field label="Limite (opcional)">
            <input type="text" value={creditLimit} onChange={e => setCreditLimit(e.target.value)} placeholder="35.000,00" className={INPUT_CLS} />
          </Field>
          {error && <p className="text-[12px] text-red-500 dark:text-red-400">{error}</p>}
          <div className="flex justify-end gap-2 pt-2">
            <button type="button" onClick={onClose} className="h-9 px-4 inline-flex items-center rounded-lg text-[12px] text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors">Cancelar</button>
            <button type="submit" disabled={saving} className="h-9 px-4 inline-flex items-center rounded-lg bg-indigo-500 hover:bg-indigo-400 disabled:opacity-60 text-white text-[12px] font-medium transition-colors">
              {saving ? 'Salvando…' : 'Salvar'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

function CardRow({ card }: { card: CreditCardOut }) {
  const limitPct = card.limit_used_pct
  return (
    <Link to={`/credit-cards/${card.id}`} className="flex items-center gap-3 p-2.5 -mx-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800/40 transition-colors">
      <FILogo slug={card.fi_logo_slug} shortName={card.financial_institution_name} size="md" />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-[13px] font-medium text-gray-900 dark:text-white">{card.name}</span>
          {card.brand && (
            <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-md text-[10px] font-medium uppercase tracking-wider bg-amber-500/10 text-amber-600 dark:text-amber-400">
              <CreditCardIcon className="w-3 h-3" /> {card.brand}
            </span>
          )}
        </div>
        <div className="text-[11px] text-gray-500 mt-0.5">
          {card.last4 ? `···· ${card.last4} · ` : ''}vence dia {card.due_day}
        </div>
      </div>
      <div className="text-right">
        <div className="text-[10px] uppercase tracking-wider text-gray-500">Fatura aberta</div>
        <div className="text-[13px] font-semibold tnum money text-amber-500 dark:text-amber-400">{fmtMoney(card.open_invoice_total, card.currency)}</div>
        {limitPct != null && <div className="text-[10px] tnum text-gray-500">{fmtPct(limitPct)} do limite</div>}
      </div>
    </Link>
  )
}

export default function CreditCards() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const [me, setMe] = useState<UserOut | null>(null)
  const [cards, setCards] = useState<CreditCardOut[]>([])
  const [institutions, setInstitutions] = useState<FinancialInstitutionOut[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<CreditCardOut | undefined>(undefined)
  useEscapeKey(() => { if (modalOpen) { setModalOpen(false); setEditing(undefined) } })

  useEffect(() => {
    api.me().then(setMe).catch(() => navigate('/login'))
  }, [navigate])

  useEffect(() => {
    if (!me) return
    setLoading(true)
    setLoadError('')
    Promise.all([api.listCreditCards(), api.listFinancialInstitutions()])
      .then(([cs, fis]) => { setCards(cs); setInstitutions(fis) })
      .catch(err => setLoadError(err instanceof Error ? err.message : 'Erro ao carregar.'))
      .finally(() => setLoading(false))
  }, [me])

  // Menu Novo → ?compose=card abre o modal de criação.
  useEffect(() => {
    if (searchParams.get('compose') === 'card' && me) {
      setEditing(undefined)
      setModalOpen(true)
      searchParams.delete('compose')
      setSearchParams(searchParams, { replace: true })
    }
  }, [searchParams, setSearchParams, me])

  const kpis = useMemo(() => cardKpis(cards), [cards])
  const canWrite = me?.role === 'admin' || me?.role === 'sysadmin'

  async function handleSave(data: CreditCardPayload) {
    if (editing) {
      const updated = await api.updateCreditCard(editing.id, data)
      setCards(prev => prev.map(c => c.id === updated.id ? updated : c))
    } else {
      const created = await api.createCreditCard(data)
      setCards(prev => [...prev, created].sort((a, b) => a.name.localeCompare(b.name)))
    }
  }

  if (!me) return null

  return (
    <AppLayout user={me}>
      <div className="space-y-6">
        <Card>
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-xl font-semibold text-gray-900 dark:text-white">Cartões de crédito</h1>
              <p className="text-[12px] text-gray-500 mt-0.5">
                {cards.length} {cards.length === 1 ? 'cartão' : 'cartões'}
                {kpis.totalLimit > 0 && <> · {fmtPct(kpis.usedPct)} do limite total utilizado</>}
              </p>
            </div>
            <div className="flex items-center gap-3">
              <Link to="/accounts" className="text-[12px] text-indigo-500 dark:text-indigo-400 hover:text-indigo-400 dark:hover:text-indigo-300">← Voltar para Contas</Link>
              {canWrite && (
                <button onClick={() => { setEditing(undefined); setModalOpen(true) }} className="h-8 px-3 inline-flex items-center gap-1.5 rounded-lg text-[12px] bg-indigo-500 hover:bg-indigo-400 text-white transition-colors">
                  <Plus className="w-3.5 h-3.5" /> Novo cartão
                </button>
              )}
            </div>
          </div>
          <div className="mt-5 grid grid-cols-1 md:grid-cols-3 gap-3">
            <KpiTile label="Total em fatura aberta" value={fmtMoney(kpis.total, 'BRL')} intent="negative" />
            <KpiTile label="Limite total" value={fmtMoney(kpis.totalLimit, 'BRL')} />
            <KpiTile label="Disponível" value={fmtMoney(kpis.available, 'BRL')} intent="positive" />
          </div>
        </Card>

        <Card>
          <SectionTitle>Cartões</SectionTitle>
          {loadError ? (
            <div className="text-sm text-red-600 dark:text-red-400 text-center py-6">{loadError}</div>
          ) : loading ? (
            <div className="text-sm text-gray-400 dark:text-gray-600 text-center py-8">Carregando…</div>
          ) : cards.length === 0 ? (
            <div className="text-[12px] text-gray-400 dark:text-gray-600 text-center py-8">
              Nenhum cartão ainda{canWrite && ' — crie com "Novo cartão" ou pelo menu Novo (K)'}.
            </div>
          ) : (
            <div className="space-y-2">
              {cards.map(c => <CardRow key={c.id} card={c} />)}
            </div>
          )}
        </Card>
      </div>

      {modalOpen && institutions.length > 0 && (
        <CardModal
          initial={editing}
          institutions={institutions}
          onSave={handleSave}
          onClose={() => { setModalOpen(false); setEditing(undefined) }}
        />
      )}
    </AppLayout>
  )
}
