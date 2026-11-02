/* Spec 72 — Contas a Pagar/Receber (/scheduled-transactions).
 *
 * Sem protótipo — design novo declarado na spec, no padrão visual de
 * Movimentações / detalhe do cartão: PageHeader, 4 KPIs do mês (a pagar,
 * a receber, líquido, em atraso — de /forecast), card de fluxo previsto
 * (3 meses, quebra por conta prevista), e duas abas:
 *
 * - Próximos vencimentos: atrasadas + do mês corrente até o fim da
 *   previsão, agrupadas por mês, com badge de status e ações manuais
 *   (Marcar pago · Adiar · Cancelar · Editar);
 * - Recorrências: CRUD das regras (editar · pausar/reativar · excluir).
 *
 * Escrita só pra admin/sysadmin (o backend devolve 403 pro member); o
 * member vê tudo em modo leitura. Menu Novo → ?compose=scheduled.
 */
import { Fragment, useCallback, useEffect, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { Loader2, MoreHorizontal, Plus, Repeat } from 'lucide-react'
import {
  api, type AccountOut, type CategoryOut, type ForecastOut, type PartyOut,
  type RecurrenceRuleOut, type ScheduledTransactionOut, type TransactionOut, type UserOut,
} from '../lib/api'
import AppLayout from '../components/AppLayout'
import { Card, GroupingToggle, PageHeader, SectionTitle } from '../components/ui'
import { fmtBRL } from '../lib/money'
import { todayISO } from '../lib/format'
import { useEscapeKey } from '../lib/useEscapeKey'
import { fmtMoney } from '../components/TransactionComposers'
import ScheduledComposer, {
  FREQUENCY_LABELS, MONTH_LABELS, type ScheduledComposerMode,
} from '../components/ScheduledComposer'

const MONTH_NAMES = MONTH_LABELS
const FORECAST_MONTHS = 3

export function fmtDate(iso: string) {
  const [y, m, d] = iso.split('-')
  return `${d}/${m}/${y}`
}

function fmtDay(iso: string) {
  const [, m, d] = iso.split('-')
  return `${d}/${m}`
}

function monthLabel(ym: string) {
  const [y, m] = ym.split('-')
  return `${MONTH_NAMES[parseInt(m, 10) - 1]} · ${y}`
}

/** Último dia do mês `offset` meses à frente de hoje (local, sem UTC). */
export function endOfMonthISO(offset: number, base = new Date()): string {
  return todayISO(new Date(base.getFullYear(), base.getMonth() + offset + 1, 0))
}

export function startOfMonthISO(base = new Date()): string {
  return todayISO(new Date(base.getFullYear(), base.getMonth(), 1))
}

/** Agrupa por mês do vencimento, ordem crescente (atrasadas primeiro). */
export function groupByDueMonth(rows: ScheduledTransactionOut[]): { ym: string; items: ScheduledTransactionOut[] }[] {
  const out = new Map<string, ScheduledTransactionOut[]>()
  for (const r of [...rows].sort((a, b) => a.due_date.localeCompare(b.due_date) || a.description.localeCompare(b.description))) {
    const ym = r.due_date.slice(0, 7)
    if (!out.has(ym)) out.set(ym, [])
    out.get(ym)!.push(r)
  }
  return [...out.keys()].sort().map(ym => ({ ym, items: out.get(ym)! }))
}

export function ruleSchedule(r: Pick<RecurrenceRuleOut, 'frequency' | 'day_of_month' | 'month' | 'installment_total' | 'installment_paid'>): string {
  if (r.frequency === 'YEARLY') return `Anual · ${String(r.day_of_month).padStart(2, '0')}/${String(r.month).padStart(2, '0')}`
  if (r.frequency === 'INSTALLMENT') return `Parcelada · ${r.installment_total}x · dia ${r.day_of_month}`
  return `Mensal · dia ${r.day_of_month}`
}

const STATUS_META: Record<ScheduledTransactionOut['display_status'], { label: string; cls: string }> = {
  PENDING: { label: 'A vencer', cls: 'bg-indigo-500/10 text-indigo-600 dark:text-indigo-300' },
  OVERDUE: { label: 'Em atraso', cls: 'bg-amber-500/15 text-amber-700 dark:text-amber-300' },
  PAID: { label: 'Pago', cls: 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400' },
  CANCELED: { label: 'Cancelado', cls: 'bg-gray-100 dark:bg-gray-800 text-gray-500 line-through' },
}

export function StatusBadge({ status }: { status: ScheduledTransactionOut['display_status'] }) {
  const m = STATUS_META[status]
  return <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium ${m.cls}`}>{m.label}</span>
}

type Tab = 'upcoming' | 'rules'

type OccAction = 'pay' | 'postpone' | 'cancel' | 'edit' | 'unpay'

type Dialog =
  | { kind: 'pay'; occ: ScheduledTransactionOut }
  | { kind: 'postpone'; occ: ScheduledTransactionOut }
  | { kind: 'cancel'; occ: ScheduledTransactionOut }
  | { kind: 'unpay'; occ: ScheduledTransactionOut }
  | { kind: 'delete-rule'; rule: RecurrenceRuleOut }
  | null

const MENU_WIDTH = 176
const MENU_ITEM_H = 30

/** Menu "Ações" renderizado num portal com position: fixed — fora do
 * wrapper overflow-x-auto da tabela, que cortava o menu nas últimas linhas
 * (audit #22). Abre pra cima quando não cabe embaixo. Fecha com ESC,
 * clique fora, scroll ou resize. */
function ActionsMenu({ anchor, items, onPick, onClose }: {
  anchor: DOMRect
  items: { kind: OccAction; label: string; danger?: boolean }[]
  onPick: (kind: OccAction) => void
  onClose: () => void
}) {
  useEscapeKey(onClose)
  useEffect(() => {
    window.addEventListener('resize', onClose)
    window.addEventListener('scroll', onClose, true)
    return () => {
      window.removeEventListener('resize', onClose)
      window.removeEventListener('scroll', onClose, true)
    }
  }, [onClose])
  const height = items.length * MENU_ITEM_H + 8
  const vh = window.innerHeight || 0
  const up = vh > 0 && anchor.bottom + 4 + height > vh && anchor.top - 4 - height >= 0
  const top = up ? anchor.top - 4 - height : anchor.bottom + 4
  const left = Math.max(8, anchor.right - MENU_WIDTH)
  return createPortal(
    <>
      <div className="fixed inset-0 z-[58]" onMouseDown={onClose} data-testid="actions-menu-backdrop" />
      <div role="menu" aria-label="Ações da conta" style={{ position: 'fixed', top, left, width: MENU_WIDTH }}
        className="z-[59] rounded-lg border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 shadow-lg py-1 text-[12px] text-left">
        {items.map(it => (
          <button key={it.kind} type="button" role="menuitem" onClick={() => onPick(it.kind)}
            className={`w-full text-left px-3 py-1.5 hover:bg-gray-100 dark:hover:bg-gray-800 ${it.danger ? 'text-red-600 dark:text-red-400' : 'text-gray-700 dark:text-gray-200'}`}>
            {it.label}
          </button>
        ))}
      </div>
    </>,
    document.body,
  )
}

export default function ScheduledTransactions() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const [me, setMe] = useState<UserOut | null>(null)
  const [accounts, setAccounts] = useState<AccountOut[]>([])
  const [categories, setCategories] = useState<CategoryOut[]>([])
  const [parties, setParties] = useState<PartyOut[]>([])
  const [rows, setRows] = useState<ScheduledTransactionOut[]>([])
  const [rules, setRules] = useState<RecurrenceRuleOut[]>([])
  const [forecast, setForecast] = useState<ForecastOut | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [lookupError, setLookupError] = useState('')
  const [toast, setToast] = useState('')
  const [tab, setTab] = useState<Tab>('upcoming')
  const [showDone, setShowDone] = useState(false)
  const [composer, setComposer] = useState<ScheduledComposerMode | null>(null)
  const [dialog, setDialog] = useState<Dialog>(null)
  const [menuFor, setMenuFor] = useState<{ id: string; rect: DOMRect } | null>(null)
  const [busyRule, setBusyRule] = useState<string | null>(null)

  const canWrite = me?.role === 'admin' || me?.role === 'sysadmin'

  useEffect(() => {
    api.me().then(setMe).catch(() => navigate('/login'))
  }, [navigate])

  // Cadastros (contas/categorias/parties) carregam à parte: uma falha aqui
  // vira aviso inline e NÃO esconde as listas que carregaram (audit #23).
  useEffect(() => {
    if (!me) return
    Promise.allSettled([api.listAccounts(), api.listCategories(), api.listParties()])
      .then(([accs, cats, ps]) => {
        if (accs.status === 'fulfilled') setAccounts(accs.value)
        if (cats.status === 'fulfilled') setCategories(cats.value)
        if (ps.status === 'fulfilled') setParties(ps.value)
        const failed = [
          accs.status === 'rejected' ? 'contas' : null,
          cats.status === 'rejected' ? 'categorias' : null,
          ps.status === 'rejected' ? 'fornecedores/clientes' : null,
        ].filter(Boolean)
        setLookupError(failed.length ? `Não deu pra carregar ${failed.join(', ')} — os seletores do formulário podem vir incompletos.` : '')
      })
  }, [me])

  const reload = useCallback(async () => {
    // Lista tudo o que já foi materializado (até hoje + 90 dias), não só a
    // janela da previsão — senão um vencimento já gerado fica escondido.
    const from = startOfMonthISO()
    const [inWindow, overdue, rs, fc] = await Promise.all([
      api.listScheduled({ from }),
      api.listScheduled({ overdue: true }),
      api.listRecurrenceRules(),
      api.scheduledForecast(FORECAST_MONTHS),
    ])
    const seen = new Set(inWindow.map(r => r.id))
    setRows([...overdue.filter(r => !seen.has(r.id)), ...inWindow])
    setRules(rs)
    setForecast(fc)
  }, [])

  useEffect(() => {
    if (!me) return
    setLoadError('')
    reload()
      .catch(err => setLoadError(err instanceof Error ? err.message : 'Erro ao carregar.'))
      .finally(() => setLoading(false))
  }, [me, reload])

  // Menu Novo → ?compose=scheduled
  useEffect(() => {
    if (!me || searchParams.get('compose') !== 'scheduled') return
    if (canWrite) setComposer({ kind: 'new' })
    const next = new URLSearchParams(searchParams)
    next.delete('compose')
    setSearchParams(next, { replace: true })
  }, [searchParams, setSearchParams, me, canWrite])

  /** Depois de um write que deu certo: falha no reload vai pro toast. */
  function afterWrite() {
    return reload().catch(err => setToast(`Salvo, mas a lista não recarregou: ${err instanceof Error ? err.message : 'erro'}`))
  }

  const visible = useMemo(
    () => showDone ? rows : rows.filter(r => r.status === 'PENDING'),
    [rows, showDone],
  )
  const grouped = useMemo(() => groupByDueMonth(visible), [visible])
  const pendingCount = rows.filter(r => r.status === 'PENDING').length
  const thisMonth = forecast?.months[0]
  const overdue = forecast?.overdue
  const overdueBrl = (overdue?.payable.brl ?? 0) + (overdue?.receivable.brl ?? 0)

  async function toggleRule(rule: RecurrenceRuleOut) {
    setBusyRule(rule.id)
    try {
      await api.updateRecurrenceRule(rule.id, { is_active: !rule.is_active })
      await afterWrite()
    } catch (err) {
      setToast(err instanceof Error ? err.message : 'Erro ao atualizar a recorrência.')
    } finally {
      setBusyRule(null)
    }
  }

  if (!me) return null

  return (
    <AppLayout user={me}>
      <div className="space-y-6">
        <PageHeader
          title="Contas a Pagar/Receber"
          count={pendingCount}
          countLabel={`pendentes · ${rules.filter(r => r.is_active).length} recorrências ativas`}
          action={canWrite ? (
            <button onClick={() => setComposer({ kind: 'new' })}
              className="h-8 px-3 inline-flex items-center gap-1.5 rounded-lg text-[12px] bg-indigo-500 hover:bg-indigo-400 text-white transition-colors">
              <Plus className="w-3.5 h-3.5" /> Nova conta
            </button>
          ) : undefined}
        />

        <div className="grid grid-cols-12 gap-4">
          <Card className="col-span-12 lg:col-span-3">
            <SectionTitle>A pagar · mês</SectionTitle>
            <div className="text-2xl font-semibold tnum money text-red-500 dark:text-red-400" data-testid="kpi-payable">
              {fmtBRL(thisMonth?.payable.brl ?? 0, { compact: true })}
            </div>
            <div className="text-[11px] text-gray-500 mt-1">pendente · em BRL</div>
          </Card>
          <Card className="col-span-12 lg:col-span-3">
            <SectionTitle>A receber · mês</SectionTitle>
            <div className="text-2xl font-semibold tnum money text-emerald-500 dark:text-emerald-400" data-testid="kpi-receivable">
              {fmtBRL(thisMonth?.receivable.brl ?? 0, { compact: true })}
            </div>
            <div className="text-[11px] text-gray-500 mt-1">pendente · em BRL</div>
          </Card>
          <Card className="col-span-12 lg:col-span-3">
            <SectionTitle>Líquido · mês</SectionTitle>
            <div className={`text-2xl font-semibold tnum money ${(thisMonth?.net.brl ?? 0) >= 0 ? 'text-emerald-500 dark:text-emerald-400' : 'text-red-500 dark:text-red-400'}`} data-testid="kpi-net">
              {fmtBRL(thisMonth?.net.brl ?? 0, { compact: true, sign: true })}
            </div>
            <div className="text-[11px] text-gray-500 mt-1">{forecast?.fx_rate ? `USD @ PTAX ${forecast.fx_rate.toLocaleString('pt-BR')}` : 'a receber − a pagar'}</div>
          </Card>
          <Card className="col-span-12 lg:col-span-3">
            <SectionTitle>Em atraso</SectionTitle>
            <div className={`text-2xl font-semibold tnum ${(overdue?.count ?? 0) > 0 ? 'text-amber-500 dark:text-amber-400' : 'text-gray-500'}`} data-testid="kpi-overdue">
              {overdue?.count ?? 0}
            </div>
            <div className="text-[11px] text-gray-500 mt-1 tnum money">
              {(overdue?.count ?? 0) > 0 ? `${fmtBRL(overdueBrl, { compact: true })} vencidos` : 'nada vencido'}
            </div>
          </Card>
        </div>

        {forecast && <ForecastCard forecast={forecast} />}

        <Card padding="p-3">
          <div className="flex items-center justify-between gap-3 flex-wrap px-1 pb-3">
            <GroupingToggle value={tab} onChange={v => setTab(v as Tab)} options={[
              { id: 'upcoming', label: 'Próximos vencimentos' },
              { id: 'rules', label: `Recorrências (${rules.length})` },
            ]} />
            {tab === 'upcoming' ? (
              <label className="inline-flex items-center gap-1.5 text-[11px] text-gray-500 cursor-pointer">
                <input type="checkbox" checked={showDone} onChange={e => setShowDone(e.target.checked)} />
                mostrar pagas e canceladas
              </label>
            ) : canWrite && (
              <button onClick={() => setComposer({ kind: 'new', frequency: 'MONTHLY' })}
                className="h-7 px-2 inline-flex items-center gap-1 rounded-md text-[11px] bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700">
                <Plus className="w-3 h-3" /> Nova recorrência
              </button>
            )}
          </div>

          {lookupError && (
            <div className="mx-1 mb-3 px-3 py-2 rounded-md text-[12px] bg-amber-500/10 text-amber-700 dark:text-amber-300" role="alert" data-testid="lookup-error">
              {lookupError}
            </div>
          )}
          {loadError ? (
            <div className="text-sm text-red-600 dark:text-red-400 text-center py-6">{loadError}</div>
          ) : loading ? (
            <div className="text-sm text-gray-400 dark:text-gray-600 text-center py-8">Carregando…</div>
          ) : tab === 'upcoming' ? (
            visible.length === 0 ? (
              <div className="text-[12px] text-gray-400 dark:text-gray-600 text-center py-10">
                Nenhuma conta pendente nos próximos {FORECAST_MONTHS} meses — crie pelo menu Novo → Conta a pagar/receber.
              </div>
            ) : (
              <div className="overflow-x-auto -mx-1">
                <table className="w-full text-[12px]">
                  <thead>
                    <tr className="text-[10px] uppercase tracking-wider text-gray-500">
                      <th className="text-left font-medium px-2 py-2">Vencimento</th>
                      <th className="text-left font-medium px-2 py-2">Descrição</th>
                      <th className="text-left font-medium px-2 py-2">Categoria</th>
                      <th className="text-left font-medium px-2 py-2">Conta prevista</th>
                      <th className="text-right font-medium px-2 py-2">Valor</th>
                      <th className="text-center font-medium px-2 py-2">Status</th>
                      <th className="px-2" />
                    </tr>
                  </thead>
                  <tbody>
                    {grouped.map((g, gi) => (
                      <Fragment key={g.ym}>
                        <tr><td colSpan={7} className="p-0"><MonthHeader ym={g.ym} first={gi === 0} /></td></tr>
                        {g.items.map(o => (
                          <OccurrenceRow key={o.id} o={o} canWrite={canWrite}
                            menuOpen={menuFor?.id === o.id}
                            onOpenMenu={rect => setMenuFor(menuFor?.id === o.id ? null : { id: o.id, rect })}
                            onAction={kind => {
                              setMenuFor(null)
                              if (kind === 'edit') setComposer({ kind: 'occurrence', occ: o })
                              else setDialog({ kind, occ: o })
                            }}
                          />
                        ))}
                      </Fragment>
                    ))}
                  </tbody>
                </table>
              </div>
            )
          ) : (
            <RulesTable rules={rules} canWrite={canWrite} busyRule={busyRule}
              onEdit={r => setComposer({ kind: 'rule', rule: r })}
              onToggle={toggleRule}
              onDelete={r => setDialog({ kind: 'delete-rule', rule: r })}
            />
          )}
        </Card>
      </div>

      {composer && (
        <ScheduledComposer
          mode={composer} accounts={accounts} categories={categories} parties={parties}
          onCreateOneOff={async d => { const r = await api.createScheduled(d); await afterWrite(); return r }}
          onCreateRule={async d => { const r = await api.createRecurrenceRule(d); await afterWrite(); return r }}
          onUpdateRule={async (id, d) => { const r = await api.updateRecurrenceRule(id, d); await afterWrite(); return r }}
          onUpdateOccurrence={async (id, d) => { const r = await api.updateScheduled(id, d); await afterWrite(); return r }}
          onClose={() => setComposer(null)}
        />
      )}

      {dialog?.kind === 'pay' && (
        <PayDialog occ={dialog.occ} onClose={() => setDialog(null)}
          onConfirm={async (paidAt, txId) => { await api.payScheduled(dialog.occ.id, { paid_at: paidAt, transaction_id: txId }); await afterWrite() }} />
      )}
      {dialog?.kind === 'postpone' && (
        <PostponeDialog occ={dialog.occ} onClose={() => setDialog(null)}
          onConfirm={async due => { await api.postponeScheduled(dialog.occ.id, due); await afterWrite() }} />
      )}
      {dialog?.kind === 'cancel' && (
        <ConfirmDialog title="Cancelar conta?" confirmLabel="Cancelar conta" danger
          body={<>{dialog.occ.description} · vence {fmtDate(dialog.occ.due_date)} · {fmtMoney(dialog.occ.signed_amount, dialog.occ.currency, { sign: true })}</>}
          detail={dialog.occ.recurrence_rule_id ? 'Só esta ocorrência — a recorrência continua gerando as próximas.' : undefined}
          onClose={() => setDialog(null)}
          onConfirm={async () => { await api.cancelScheduled(dialog.occ.id); await afterWrite() }} />
      )}
      {dialog?.kind === 'unpay' && (
        <ConfirmDialog title="Desfazer pagamento?" confirmLabel="Desfazer pagamento"
          body={<>{dialog.occ.description} · vence {fmtDate(dialog.occ.due_date)} · pago em {dialog.occ.paid_at ? fmtDate(dialog.occ.paid_at) : '—'}</>}
          detail={dialog.occ.paid_by_transaction_id
            ? 'A conta volta a pendente e perde o vínculo com a movimentação (a movimentação continua no extrato).'
            : 'A conta volta a pendente.'}
          onClose={() => setDialog(null)}
          onConfirm={async () => { await api.unpayScheduled(dialog.occ.id); await afterWrite() }} />
      )}
      {menuFor && (() => {
        const o = rows.find(r => r.id === menuFor.id)
        if (!o) return null
        const items: { kind: OccAction; label: string; danger?: boolean }[] = o.status === 'PENDING'
          ? [{ kind: 'edit', label: 'Editar' }, { kind: 'postpone', label: 'Adiar' }, { kind: 'cancel', label: 'Cancelar', danger: true }]
          : o.status === 'PAID' ? [{ kind: 'unpay', label: 'Desfazer pagamento' }] : []
        return (
          <ActionsMenu anchor={menuFor.rect} items={items} onClose={() => setMenuFor(null)}
            onPick={kind => {
              setMenuFor(null)
              if (kind === 'edit') setComposer({ kind: 'occurrence', occ: o })
              else setDialog({ kind, occ: o })
            }} />
        )
      })()}
      {dialog?.kind === 'delete-rule' && (
        <ConfirmDialog title="Excluir recorrência?" confirmLabel="Excluir" danger
          body={<>{dialog.rule.description} · {ruleSchedule(dialog.rule)}</>}
          detail="As ocorrências pendentes (inclusive em atraso) somem; as pagas e canceladas ficam no histórico como avulsas. Pra só parar de gerar, use Pausar."
          onClose={() => setDialog(null)}
          onConfirm={async () => { await api.deleteRecurrenceRule(dialog.rule.id); await afterWrite() }} />
      )}

      {toast && (
        <div className="fixed bottom-4 right-4 z-[70] max-w-sm bg-red-600 text-white text-[12px] rounded-lg shadow-lg px-4 py-3" role="status">
          {toast}
          <button onClick={() => setToast('')} className="ml-3 underline">fechar</button>
        </div>
      )}
    </AppLayout>
  )
}

function MonthHeader({ ym, first }: { ym: string; first?: boolean }) {
  return (
    <div className={`px-2 py-2 ${first ? '' : 'mt-3'} text-[10px] uppercase tracking-wider font-semibold text-gray-500 sticky top-0 bg-gray-50 dark:bg-gray-950 z-[1] border-b border-gray-200 dark:border-gray-800`}>
      {monthLabel(ym)}
    </div>
  )
}

function ForecastCard({ forecast }: { forecast: ForecastOut }) {
  return (
    <Card>
      <SectionTitle>Fluxo previsto · {forecast.months.length} meses</SectionTitle>
      <table className="w-full text-[12px]" data-testid="forecast-table">
        <thead>
          <tr className="text-[10px] uppercase tracking-wider text-gray-500">
            <th className="text-left font-medium px-2 py-1.5">Mês</th>
            <th className="text-right font-medium px-2 py-1.5">A pagar</th>
            <th className="text-right font-medium px-2 py-1.5">A receber</th>
            <th className="text-right font-medium px-2 py-1.5">Líquido</th>
          </tr>
        </thead>
        <tbody>
          {forecast.months.map(m => (
            <Fragment key={m.month}>
              <tr className="border-t border-gray-100 dark:border-gray-800">
                <td className="px-2 py-1.5 font-medium text-gray-900 dark:text-white">{monthLabel(m.month)}</td>
                <td className="px-2 text-right tnum money text-red-500 dark:text-red-400">{fmtBRL(m.payable.brl)}</td>
                <td className="px-2 text-right tnum money text-emerald-500 dark:text-emerald-400">{fmtBRL(m.receivable.brl)}</td>
                <td className={`px-2 text-right tnum money font-medium ${m.net.brl >= 0 ? 'text-emerald-500 dark:text-emerald-400' : 'text-red-500 dark:text-red-400'}`}>{fmtBRL(m.net.brl, { sign: true })}</td>
              </tr>
              {(forecast.card_invoices ?? []).filter(i => i.due_date.slice(0, 7) === m.month).map(i => (
                <tr key={i.invoice_id} className="text-[11px] text-gray-500" data-testid={`forecast-invoice-${i.invoice_id}`}>
                  <td className="pl-6 pr-2 py-1">
                    <Link to={`/credit-cards/${i.card_id}`} className="hover:text-indigo-500" title={i.status === 'OPEN' ? 'fatura aberta: soma dos lançamentos conhecidos' : 'fatura fechada'}>
                      {i.label}
                    </Link>
                  </td>
                  <td className="px-2 text-right tnum money">{fmtMoney(i.amount, i.currency)}</td>
                  <td className="px-2 text-right">—</td>
                  <td className="px-2 text-right">—</td>
                </tr>
              ))}
              {m.by_account.map(a => (
                <tr key={a.account_id} className="text-[11px] text-gray-500">
                  <td className="pl-6 pr-2 py-1">{a.account_name}</td>
                  <td className="px-2 text-right tnum money">{a.payable ? fmtMoney(a.payable, a.currency) : '—'}</td>
                  <td className="px-2 text-right tnum money">{a.receivable ? fmtMoney(a.receivable, a.currency) : '—'}</td>
                  <td className="px-2 text-right tnum money">{fmtMoney(a.net, a.currency, { sign: true })}</td>
                </tr>
              ))}
            </Fragment>
          ))}
        </tbody>
      </table>
    </Card>
  )
}

function OccurrenceRow({ o, canWrite, menuOpen, onOpenMenu, onAction }: {
  o: ScheduledTransactionOut
  canWrite: boolean
  menuOpen: boolean
  onOpenMenu: (rect: DOMRect) => void
  onAction: (kind: OccAction) => void
}) {
  const pending = o.status === 'PENDING'
  const hasMenu = pending || o.status === 'PAID'
  return (
    <tr className={`border-t border-gray-100 dark:border-gray-800 ${o.status === 'CANCELED' ? 'opacity-60' : ''}`} data-testid={`occ-${o.id}`}>
      <td className={`px-2 py-2 tnum ${o.is_overdue ? 'text-amber-600 dark:text-amber-400 font-medium' : 'text-gray-400'}`}>{fmtDay(o.due_date)}</td>
      <td className="px-2">
        <div className="flex items-center gap-1.5 text-gray-900 dark:text-white">
          <span>{o.description}</span>
          {o.installment_number && o.installment_total && (
            <span className="text-[10px] text-gray-500 tnum">parcela {o.installment_number}/{o.installment_total}</span>
          )}
          {o.recurrence_rule_id && !o.installment_number && (
            <span title={o.frequency ? FREQUENCY_LABELS[o.frequency] : 'Recorrência'}><Repeat className="w-3 h-3 text-gray-400" aria-label="Recorrente" /></span>
          )}
        </div>
        {(o.party_name || o.notes) && (
          <div className="text-[10px] text-gray-500">{[o.party_name, o.notes].filter(Boolean).join(' · ')}</div>
        )}
        {o.status === 'PAID' && (
          <div className="text-[10px] text-gray-500">
            pago em {o.paid_at ? fmtDate(o.paid_at) : '—'}{o.paid_by_transaction_id ? ' · vinculado a movimentação' : ' · sem vínculo'}
          </div>
        )}
      </td>
      <td className="px-2">
        {o.category_name ? (
          <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px]"
            style={{ background: (o.category_color ?? '#6b7280') + '22', color: o.category_color ?? '#6b7280' }}>
            <span className="w-1.5 h-1.5 rounded-full" style={{ background: o.category_color ?? '#6b7280' }} />
            {o.category_name}
          </span>
        ) : (
          <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] bg-gray-100 dark:bg-gray-800/60 text-gray-500 italic">Sem categoria</span>
        )}
      </td>
      <td className="px-2 text-[11px] text-gray-500">{o.expected_account_name ?? '—'}</td>
      <td className={`px-2 text-right tnum money font-medium ${o.direction === 'RECEIVABLE' ? 'text-emerald-500 dark:text-emerald-400' : 'text-gray-900 dark:text-white'}`}>
        {fmtMoney(o.signed_amount, o.currency, { sign: true })}
      </td>
      <td className="px-2 text-center"><StatusBadge status={o.display_status} /></td>
      <td className="px-2 text-gray-500 whitespace-nowrap text-right">
        {canWrite && hasMenu && (
          <>
            {pending && (
              <button type="button" onClick={() => onAction('pay')}
                className="h-6 px-2 mr-1 inline-flex items-center rounded-md text-[10px] bg-indigo-500/10 text-indigo-600 dark:text-indigo-300 hover:bg-indigo-500/20">
                Marcar pago
              </button>
            )}
            <button type="button" onClick={e => onOpenMenu(e.currentTarget.getBoundingClientRect())}
              aria-label="Ações" aria-haspopup="menu" aria-expanded={menuOpen}
              className="p-1 rounded hover:bg-gray-100 dark:hover:bg-gray-800 align-middle">
              <MoreHorizontal className="w-4 h-4" />
            </button>
          </>
        )}
      </td>
    </tr>
  )
}

function RulesTable({ rules, canWrite, busyRule, onEdit, onToggle, onDelete }: {
  rules: RecurrenceRuleOut[]
  canWrite: boolean
  busyRule: string | null
  onEdit: (r: RecurrenceRuleOut) => void
  onToggle: (r: RecurrenceRuleOut) => void
  onDelete: (r: RecurrenceRuleOut) => void
}) {
  if (rules.length === 0) {
    return (
      <div className="text-[12px] text-gray-400 dark:text-gray-600 text-center py-10">
        Nenhuma recorrência — aluguel, salário, financiamento… crie em "Nova recorrência".
      </div>
    )
  }
  return (
    <div className="overflow-x-auto -mx-1">
      <table className="w-full text-[12px]">
        <thead>
          <tr className="text-[10px] uppercase tracking-wider text-gray-500">
            <th className="text-left font-medium px-2 py-2">Descrição</th>
            <th className="text-left font-medium px-2 py-2">Frequência</th>
            <th className="text-left font-medium px-2 py-2">Conta prevista</th>
            <th className="text-right font-medium px-2 py-2">Valor</th>
            <th className="text-left font-medium px-2 py-2">Próximo</th>
            <th className="text-center font-medium px-2 py-2">Status</th>
            <th className="px-2" />
          </tr>
        </thead>
        <tbody>
          {rules.map(r => {
            const signed = r.direction === 'PAYABLE' ? -r.amount : r.amount
            return (
              <tr key={r.id} className="border-t border-gray-100 dark:border-gray-800" data-testid={`rule-${r.id}`}>
                <td className="px-2 py-2">
                  <div className="text-gray-900 dark:text-white">{r.description}</div>
                  <div className="text-[10px] text-gray-500">
                    {[r.direction === 'PAYABLE' ? 'A pagar' : 'A receber', r.party_name, r.category_name].filter(Boolean).join(' · ')}
                  </div>
                </td>
                <td className="px-2 text-gray-700 dark:text-gray-300">
                  {ruleSchedule(r)}
                  {r.end_date && <div className="text-[10px] text-gray-500">até {fmtDate(r.end_date)}</div>}
                </td>
                <td className="px-2 text-[11px] text-gray-500">{r.expected_account_name ?? '—'}</td>
                <td className={`px-2 text-right tnum money font-medium ${signed > 0 ? 'text-emerald-500 dark:text-emerald-400' : 'text-gray-900 dark:text-white'}`}>
                  {fmtMoney(signed, r.currency, { sign: true })}
                </td>
                <td className="px-2 tnum text-gray-500">{r.next_due_date ? fmtDate(r.next_due_date) : '—'}</td>
                <td className="px-2 text-center">
                  <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium ${r.is_active ? 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400' : 'bg-gray-100 dark:bg-gray-800 text-gray-500'}`}>
                    {r.is_active ? 'Ativa' : 'Pausada'}
                  </span>
                </td>
                <td className="px-2 text-right whitespace-nowrap">
                  {canWrite && (
                    <div className="inline-flex gap-1">
                      <button type="button" onClick={() => onEdit(r)} className="h-6 px-2 rounded-md text-[10px] bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700">Editar</button>
                      <button type="button" onClick={() => onToggle(r)} disabled={busyRule === r.id}
                        className="h-6 px-2 inline-flex items-center gap-1 rounded-md text-[10px] bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700 disabled:opacity-60">
                        {busyRule === r.id && <Loader2 className="w-3 h-3 animate-spin" />}
                        {r.is_active ? 'Pausar' : 'Reativar'}
                      </button>
                      <button type="button" onClick={() => onDelete(r)} className="h-6 px-2 rounded-md text-[10px] text-red-600 dark:text-red-400 hover:bg-red-500/10">Excluir</button>
                    </div>
                  )}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

/* ── dialogs ─────────────────────────────────────────────────────────── */

function DialogShell({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/40 p-4">
      <div role="dialog" aria-label={label} className="w-full max-w-md bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-700 shadow-xl p-6">
        {children}
      </div>
    </div>
  )
}

function DialogButtons({ onClose, onConfirm, busy, disabled, confirmLabel, danger }: {
  onClose: () => void
  onConfirm: () => void
  busy: boolean
  disabled?: boolean
  confirmLabel: string
  danger?: boolean
}) {
  return (
    <div className="flex justify-end gap-3 mt-5">
      <button type="button" onClick={onClose} className="px-4 py-2 rounded-lg text-sm text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors">Voltar</button>
      <button type="button" onClick={onConfirm} disabled={busy || disabled}
        className={`px-4 py-2 inline-flex items-center gap-1.5 rounded-lg text-white text-sm font-medium disabled:opacity-60 transition-colors ${danger ? 'bg-red-600 hover:bg-red-500' : 'bg-indigo-500 hover:bg-indigo-400'}`}>
        {busy && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
        {confirmLabel}
      </button>
    </div>
  )
}

function useAsyncAction(onClose: () => void) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  async function run(fn: () => Promise<void>) {
    setBusy(true)
    setError('')
    try {
      await fn()
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Erro.')
    } finally {
      setBusy(false)
    }
  }
  return { busy, error, run }
}

function PayDialog({ occ, onClose, onConfirm }: {
  occ: ScheduledTransactionOut
  onClose: () => void
  onConfirm: (paidAt: string, txId: string | null) => Promise<void>
}) {
  const [paidAt, setPaidAt] = useState(todayISO())
  const [txId, setTxId] = useState('')
  const [candidates, setCandidates] = useState<TransactionOut[] | null>(null)
  const [candError, setCandError] = useState('')
  const { busy, error, run } = useAsyncAction(onClose)
  useEscapeKey(onClose)

  useEffect(() => {
    api.scheduledCandidates(occ.id)
      .then(setCandidates)
      .catch(err => { setCandidates([]); setCandError(err instanceof Error ? err.message : 'Erro ao buscar movimentações.') })
  }, [occ.id])

  function pickTx(id: string) {
    setTxId(id)
    const tx = candidates?.find(c => c.id === id)
    if (tx) setPaidAt(tx.event_date)
  }

  return (
    <DialogShell label="Marcar pago">
      <h2 className="text-base font-semibold text-gray-900 dark:text-white mb-1">Marcar pago</h2>
      <p className="text-sm text-gray-500 dark:text-gray-400">
        {occ.description} · vence {fmtDate(occ.due_date)} · {fmtMoney(occ.signed_amount, occ.currency, { sign: true })}
      </p>
      <div className="mt-4 space-y-3">
        <label className="block">
          <span className="block text-[10px] uppercase tracking-wider font-semibold text-gray-500 mb-1">Movimentação que quitou</span>
          <select value={txId} onChange={e => pickTx(e.target.value)} aria-label="Movimentação que quitou"
            disabled={candidates === null}
            className="w-full h-9 px-3 text-[13px] rounded-md bg-gray-50 dark:bg-gray-800/50 border border-gray-200 dark:border-gray-800 text-gray-900 dark:text-white">
            <option value="">{candidates === null ? 'Carregando…' : 'Sem vincular movimentação'}</option>
            {candidates?.map(t => (
              <option key={t.id} value={t.id}>
                {fmtDate(t.event_date)} · {t.description} · {fmtMoney(t.amount, t.currency, { sign: true })} · {t.account_name ?? t.card_name}
              </option>
            ))}
          </select>
        </label>
        {candError && <p className="text-[11px] text-red-600 dark:text-red-400">{candError}</p>}
        <label className="block">
          <span className="block text-[10px] uppercase tracking-wider font-semibold text-gray-500 mb-1">Data do pagamento</span>
          <input type="date" value={paidAt} onChange={e => setPaidAt(e.target.value)} aria-label="Data do pagamento"
            className="w-full h-9 px-3 text-[13px] rounded-md bg-gray-50 dark:bg-gray-800/50 border border-gray-200 dark:border-gray-800 text-gray-900 dark:text-white" />
        </label>
        {!txId && (
          <p className="text-[12px] text-amber-600 dark:text-amber-400" data-testid="pay-no-link-warning">
            Sem vínculo: a conta fica paga, mas nada a liga a uma movimentação — o import do extrato não vai casá-la depois.
          </p>
        )}
      </div>
      {error && <p className="text-[12px] text-red-600 dark:text-red-400 mt-3" role="alert">{error}</p>}
      <DialogButtons onClose={onClose} busy={busy} disabled={!paidAt} confirmLabel="Marcar pago"
        onConfirm={() => run(() => onConfirm(paidAt, txId || null))} />
    </DialogShell>
  )
}

function PostponeDialog({ occ, onClose, onConfirm }: {
  occ: ScheduledTransactionOut
  onClose: () => void
  onConfirm: (due: string) => Promise<void>
}) {
  const [due, setDue] = useState(occ.due_date)
  const { busy, error, run } = useAsyncAction(onClose)
  useEscapeKey(onClose)
  return (
    <DialogShell label="Adiar vencimento">
      <h2 className="text-base font-semibold text-gray-900 dark:text-white mb-1">Adiar vencimento</h2>
      <p className="text-sm text-gray-500 dark:text-gray-400">{occ.description} · vence {fmtDate(occ.due_date)}</p>
      <label className="block mt-4">
        <span className="block text-[10px] uppercase tracking-wider font-semibold text-gray-500 mb-1">Novo vencimento</span>
        <input type="date" value={due} onChange={e => setDue(e.target.value)} aria-label="Novo vencimento"
          className="w-full h-9 px-3 text-[13px] rounded-md bg-gray-50 dark:bg-gray-800/50 border border-gray-200 dark:border-gray-800 text-gray-900 dark:text-white" />
      </label>
      {error && <p className="text-[12px] text-red-600 dark:text-red-400 mt-3" role="alert">{error}</p>}
      <DialogButtons onClose={onClose} busy={busy} disabled={!due || due === occ.due_date} confirmLabel="Adiar"
        onConfirm={() => run(() => onConfirm(due))} />
    </DialogShell>
  )
}

function ConfirmDialog({ title, body, detail, confirmLabel, danger, onClose, onConfirm }: {
  title: string
  body: React.ReactNode
  detail?: string
  confirmLabel: string
  danger?: boolean
  onClose: () => void
  onConfirm: () => Promise<void>
}) {
  const { busy, error, run } = useAsyncAction(onClose)
  useEscapeKey(onClose)
  return (
    <DialogShell label={title}>
      <h2 className="text-base font-semibold text-gray-900 dark:text-white mb-2">{title}</h2>
      <p className="text-sm text-gray-500 dark:text-gray-400">{body}</p>
      {detail && <p className="text-[12px] text-amber-600 dark:text-amber-400 mt-2">{detail}</p>}
      {error && <p className="text-[12px] text-red-600 dark:text-red-400 mt-3" role="alert">{error}</p>}
      <DialogButtons onClose={onClose} busy={busy} confirmLabel={confirmLabel} danger={danger} onConfirm={() => run(onConfirm)} />
    </DialogShell>
  )
}
