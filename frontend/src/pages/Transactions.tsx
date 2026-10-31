/* Spec 70 — Movimentações (/transactions), fiel ao proto MovimentacoesPage
 * (index.html:5579-5715): 4 KPIs (Entradas · período, Saídas · período,
 * Resultado, Não reconciliadas), botão "Reconciliar" no header, card de
 * filtros (busca, período, chips de Origem e Categoria), tabela agrupada
 * por mês com Data / Origem / Descrição / Categoria / Valor / Status / ⋯.
 *
 * Deltas declarados na spec 70: filtro por Fornecedor/Cliente; chips de
 * Categoria são as RAÍZES (agrupadores) — selecionar uma raiz filtra todas
 * as subs dela; período em 2 inputs de data (o app não tem DateRangeButton);
 * "Reconciliar" fica disabled até o import (spec 71).
 *
 * KPIs vêm de /transactions/summary (fluxo bruto, corta em hoje) em BRL.
 */
import { Fragment, useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Check, CreditCard as CreditCardIcon, FileText, MoreHorizontal } from 'lucide-react'
import {
  api, type AccountOut, type CategoryOut, type CreditCardOut, type InvoiceOut, type PartyOut,
  type TransactionCreatePayload, type TransactionOut, type TransactionSummaryOut,
  type TransactionUpdatePayload, type TransferPayload, type UserOut,
} from '../lib/api'
import AppLayout from '../components/AppLayout'
import { Card, FILogo, FilterGroup, MultiChips, PageHeader, SearchInput, SectionTitle, INPUT_CLS } from '../components/ui'
import { fmtBRL } from '../lib/money'
import { useEscapeKey } from '../lib/useEscapeKey'
import { CARDS_CHANGED_EVENT } from '../lib/useCardCounts'
import {
  CardTxComposer, TransactionComposer, TransferComposer, fmtMoney,
} from '../components/TransactionComposers'
import type { AttachmentDraft, PersistedAttachment } from '../components/NotesAttachmentsField'
import { todayISO } from '../lib/format'

const MONTH_NAMES = ['Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho', 'Julho', 'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro']

export function groupByMonth(rows: TransactionOut[]): { ym: string; items: TransactionOut[] }[] {
  const out = new Map<string, TransactionOut[]>()
  for (const r of rows) {
    const ym = r.event_date.slice(0, 7)
    if (!out.has(ym)) out.set(ym, [])
    out.get(ym)!.push(r)
  }
  return [...out.keys()].sort((a, b) => b.localeCompare(a)).map(ym => ({ ym, items: out.get(ym)! }))
}

/** Raízes selecionadas → ids das subs (é a sub que a tx referencia). */
export function subIdsForRoots(categories: CategoryOut[], rootIds: string[]): string[] {
  return categories.filter(c => c.parent_id && rootIds.includes(c.parent_id)).map(c => c.id)
}

function fmtDay(iso: string) {
  const [, m, d] = iso.split('-')
  return `${d}/${m}`
}

function defaultFrom(): string {
  const d = new Date()
  d.setMonth(d.getMonth() - 2, 1)
  return todayISO(d)
}

type ComposerState =
  | { kind: 'transaction'; editing?: TransactionOut }
  | { kind: 'card-tx'; editing?: TransactionOut }
  | { kind: 'transfer' }
  | null

export default function Transactions() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const [me, setMe] = useState<UserOut | null>(null)
  const [accounts, setAccounts] = useState<AccountOut[]>([])
  const [cards, setCards] = useState<CreditCardOut[]>([])
  const [invoices, setInvoices] = useState<InvoiceOut[]>([])
  const [categories, setCategories] = useState<CategoryOut[]>([])
  const [parties, setParties] = useState<PartyOut[]>([])
  // Composers leem os defaults (1ª conta/cartão) no mount — só abrem depois dos cadastros.
  const [refsLoaded, setRefsLoaded] = useState(false)
  const [rows, setRows] = useState<TransactionOut[]>([])
  const [total, setTotal] = useState(0)
  const [summary, setSummary] = useState<TransactionSummaryOut | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [toast, setToast] = useState('')

  const [sources, setSources] = useState<string[]>([])
  const [rootCats, setRootCats] = useState<string[]>([])
  const [partyId, setPartyId] = useState('')
  const [search, setSearch] = useState('')
  const [debounced, setDebounced] = useState('')
  const [from, setFrom] = useState(defaultFrom())
  const [to, setTo] = useState('')

  const [composer, setComposer] = useState<ComposerState>(null)
  const [editingAttachments, setEditingAttachments] = useState<PersistedAttachment[]>([])
  const [menuFor, setMenuFor] = useState<string | null>(null)
  const [confirmDelete, setConfirmDelete] = useState<TransactionOut | null>(null)
  const [deleting, setDeleting] = useState(false)

  useEscapeKey(() => {
    if (confirmDelete) setConfirmDelete(null)
    else if (menuFor) setMenuFor(null)
  })

  useEffect(() => {
    api.me().then(setMe).catch(() => navigate('/login'))
  }, [navigate])

  // Cadastros (uma vez)
  useEffect(() => {
    if (!me) return
    Promise.all([
      api.listAccounts(), api.listCreditCards(), api.listInvoices(),
      api.listCategories(), api.listParties(),
    ])
      .then(([accs, cs, invs, cats, ps]) => {
        setAccounts(accs); setCards(cs); setInvoices(invs); setCategories(cats); setParties(ps)
        setRefsLoaded(true)
      })
      .catch(err => setLoadError(err instanceof Error ? err.message : 'Erro ao carregar cadastros.'))
  }, [me])

  useEffect(() => {
    const t = window.setTimeout(() => setDebounced(search.trim()), 300)
    return () => window.clearTimeout(t)
  }, [search])

  const checkingIds = useMemo(() => new Set(accounts.filter(a => a.account_type === 'checking').map(a => a.id)), [accounts])
  const filters = useMemo(() => ({
    from: from || undefined,
    to: to || undefined,
    account_id: sources.filter(s => checkingIds.has(s)),
    card_id: sources.filter(s => !checkingIds.has(s)),
    category_id: rootCats.length ? subIdsForRoots(categories, rootCats) : undefined,
    party_id: partyId || undefined,
    search: debounced || undefined,
  }), [from, to, sources, checkingIds, rootCats, categories, partyId, debounced])

  const reload = useCallback(() => {
    // Raiz selecionada sem subs → nada casa; evita mandar filtro vazio (= todos).
    if (filters.category_id && filters.category_id.length === 0) {
      setRows([]); setTotal(0)
      setSummary({ inflows: { brl: 0, usd: 0 }, outflows: { brl: 0, usd: 0 }, net: { brl: 0, usd: 0 }, unreconciled_count: 0, count: 0 })
      return Promise.resolve()
    }
    return Promise.all([api.listTransactions(filters), api.transactionSummary(filters)])
      .then(([list, s]) => { setRows(list.items); setTotal(list.total); setSummary(s) })
  }, [filters])

  // Só depois dos cadastros: o filtro de categoria depende deles (evita 2 fetches).
  // "Carregando…" só na 1ª carga — refiltrar mantém a tabela na tela.
  useEffect(() => {
    if (!me || !refsLoaded) return
    setLoadError('')
    reload()
      .catch(err => setLoadError(err instanceof Error ? err.message : 'Erro ao carregar.'))
      .finally(() => setLoading(false))
  }, [me, refsLoaded, reload])

  // Menu Novo → ?compose=transaction|card-tx|transfer
  useEffect(() => {
    const c = searchParams.get('compose')
    if (!me || !refsLoaded || !c) return
    if (c === 'transaction' || c === 'card-tx' || c === 'transfer') {
      setComposer({ kind: c })
      const next = new URLSearchParams(searchParams)
      next.delete('compose')
      setSearchParams(next, { replace: true })
    }
  }, [searchParams, setSearchParams, me, refsLoaded])

  const sourceOpts = useMemo(() => [
    ...accounts.filter(a => a.account_type === 'checking' && a.is_active).map(a => ({ id: a.id, label: a.name })),
    ...cards.filter(c => c.is_active).map(c => ({ id: c.id, label: c.name })),
  ], [accounts, cards])
  const rootOpts = useMemo(() =>
    categories.filter(c => c.parent_id === null && c.is_active)
      .sort((a, b) => a.name.localeCompare(b.name))
      .map(c => ({ id: c.id, label: c.name, color: c.color })),
  [categories])
  const grouped = useMemo(() => groupByMonth(rows), [rows])
  const sourceCount = useMemo(() => new Set(rows.map(r => r.checking_account_id ?? r.credit_card_account_id)).size, [rows])

  function afterWrite() {
    window.dispatchEvent(new Event(CARDS_CHANGED_EVENT))
    api.listInvoices().then(setInvoices).catch(() => {})
    return reload()
  }

  async function handleCreate(data: TransactionCreatePayload) {
    const created = await api.createTransaction(data)
    await afterWrite()
    return created
  }
  async function handleUpdate(id: string, data: TransactionUpdatePayload) {
    const updated = await api.updateTransaction(id, data)
    await afterWrite()
    return updated
  }
  async function handleTransfer(data: TransferPayload) {
    const legs = await api.createTransfer(data)
    await afterWrite()
    return legs
  }
  async function handleUploadDrafts(entityId: string, drafts: AttachmentDraft[]) {
    const results = await Promise.allSettled(drafts.map(d => api.uploadAttachment('transaction', entityId, d.file)))
    const failed = results.map((r, i) => ({ r, name: drafts[i].name })).filter(x => x.r.status === 'rejected')
    if (failed.length) {
      throw new Error(failed.map(x => `${x.name}: ${(x.r as PromiseRejectedResult).reason?.message ?? 'erro'}`).join(' · '))
    }
  }
  async function loadAttachments(txId: string) {
    const list = await api.listAttachments('transaction', txId).catch(() => [])
    setEditingAttachments(list.map(a => ({ id: a.id, filename: a.filename, size_bytes: a.size_bytes, mime_type: a.mime_type, kind: a.kind })))
  }
  async function handleRemoveAttachment(attachmentId: string) {
    await api.deleteAttachment(attachmentId)
    if (composer && 'editing' in composer && composer.editing) await loadAttachments(composer.editing.id)
  }

  function openEdit(t: TransactionOut) {
    setMenuFor(null)
    setEditingAttachments([])
    loadAttachments(t.id)
    setComposer({ kind: t.source_type === 'CREDIT_CARD' ? 'card-tx' : 'transaction', editing: t })
  }

  async function doDelete(t: TransactionOut) {
    setDeleting(true)
    try {
      const isParent = !!t.installment_total && t.parent_transaction_id === null
      await api.deleteTransaction(t.id, isParent)
      setConfirmDelete(null)
      await afterWrite()
    } catch (err) {
      setToast(err instanceof Error ? err.message : 'Erro ao excluir.')
    } finally {
      setDeleting(false)
    }
  }

  if (!me) return null
  const editing = composer && 'editing' in composer ? composer.editing : undefined

  return (
    <AppLayout user={me}>
      <div className="space-y-6">
        <PageHeader
          title="Movimentações"
          count={total}
          countLabel={`transações · ${sourceCount} ${sourceCount === 1 ? 'fonte' : 'fontes'}`}
          action={
            <button disabled title="Chega com o import de extrato (spec 71)"
              className="h-8 px-3 inline-flex items-center gap-1.5 rounded-lg text-[12px] bg-gray-100 dark:bg-gray-800 text-gray-400 dark:text-gray-600 cursor-not-allowed">
              <FileText className="w-3.5 h-3.5" /> Reconciliar
            </button>
          }
        />

        <div className="grid grid-cols-12 gap-4">
          <Card className="col-span-12 lg:col-span-3">
            <SectionTitle>Entradas · período</SectionTitle>
            <div className="text-2xl font-semibold tnum money text-emerald-500 dark:text-emerald-400" data-testid="kpi-inflows">
              {fmtBRL(summary?.inflows.brl ?? 0, { compact: true })}
            </div>
            <div className="text-[11px] text-gray-500 mt-1">até hoje · em BRL</div>
          </Card>
          <Card className="col-span-12 lg:col-span-3">
            <SectionTitle>Saídas · período</SectionTitle>
            <div className="text-2xl font-semibold tnum money text-red-500 dark:text-red-400" data-testid="kpi-outflows">
              {fmtBRL(summary?.outflows.brl ?? 0, { compact: true })}
            </div>
            <div className="text-[11px] text-gray-500 mt-1" title="Fluxo bruto: inclui transferências e pagamentos de fatura">fluxo bruto</div>
          </Card>
          <Card className="col-span-12 lg:col-span-3">
            <SectionTitle>Resultado</SectionTitle>
            <div className={`text-2xl font-semibold tnum money ${(summary?.net.brl ?? 0) >= 0 ? 'text-emerald-500 dark:text-emerald-400' : 'text-red-500 dark:text-red-400'}`} data-testid="kpi-net">
              {fmtBRL(summary?.net.brl ?? 0, { compact: true, sign: true })}
            </div>
            <div className="text-[11px] text-gray-500 mt-1">após PTAX</div>
          </Card>
          <Card className="col-span-12 lg:col-span-3">
            <SectionTitle>Não reconciliadas</SectionTitle>
            <div className={`text-2xl font-semibold tnum ${(summary?.unreconciled_count ?? 0) > 0 ? 'text-amber-500 dark:text-amber-400' : 'text-gray-500'}`} data-testid="kpi-unreconciled">
              {summary?.unreconciled_count ?? 0}
            </div>
            <div className="text-[11px] text-gray-500 mt-1">
              {(summary?.unreconciled_count ?? 0) > 0 ? 'esperando match com extrato' : 'tudo conferido'}
            </div>
          </Card>
        </div>

        <Card padding="p-3" className="space-y-3">
          <div className="flex items-center gap-3 flex-wrap">
            <SearchInput value={search} onChange={setSearch} placeholder="Descrição…" />
            <div className="flex items-center gap-1.5 text-[11px] text-gray-500">
              <input type="date" value={from} onChange={e => setFrom(e.target.value)} aria-label="De"
                className="h-8 px-2 text-[12px] rounded-lg bg-gray-100 dark:bg-gray-900 border border-gray-200 dark:border-gray-800" />
              até
              <input type="date" value={to} onChange={e => setTo(e.target.value)} aria-label="Até"
                className="h-8 px-2 text-[12px] rounded-lg bg-gray-100 dark:bg-gray-900 border border-gray-200 dark:border-gray-800" />
            </div>
            <select value={partyId} onChange={e => setPartyId(e.target.value)} aria-label="Fornecedor/Cliente"
              className={`${INPUT_CLS} h-8 max-w-[220px] text-[12px]`}>
              <option value="">Todos fornecedores/clientes</option>
              {parties.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          </div>
          <div className="space-y-2 pt-3 border-t border-gray-200 dark:border-gray-800">
            <FilterGroup label="Origem">
              <MultiChips options={sourceOpts} selected={sources} onChange={setSources} />
            </FilterGroup>
            <FilterGroup label="Categoria">
              <MultiChips options={rootOpts} selected={rootCats} onChange={setRootCats} />
            </FilterGroup>
          </div>
        </Card>

        <Card padding="p-3">
          {loadError ? (
            <div className="text-sm text-red-600 dark:text-red-400 text-center py-6">{loadError}</div>
          ) : loading ? (
            <div className="text-sm text-gray-400 dark:text-gray-600 text-center py-8">Carregando…</div>
          ) : rows.length === 0 ? (
            <div className="text-[12px] text-gray-400 dark:text-gray-600 text-center py-10">
              Nenhuma movimentação no período — crie pelo menu Novo (M, F) ou ajuste os filtros.
            </div>
          ) : (
            <div className="overflow-x-auto -mx-1">
              <table className="w-full text-[12px]">
                <thead>
                  <tr className="text-[10px] uppercase tracking-wider text-gray-500">
                    <th className="text-left font-medium px-2 py-2">Data</th>
                    <th className="text-left font-medium px-2 py-2">Origem</th>
                    <th className="text-left font-medium px-2 py-2">Descrição</th>
                    <th className="text-left font-medium px-2 py-2">Categoria</th>
                    <th className="text-right font-medium px-2 py-2">Valor</th>
                    <th className="text-center font-medium px-2 py-2">Status</th>
                    <th className="px-2" />
                  </tr>
                </thead>
                <tbody>
                  {grouped.map((g, gi) => (
                    <Fragment key={g.ym}>
                      <tr><td colSpan={7} className="p-0"><MonthHeader ym={g.ym} first={gi === 0} /></td></tr>
                      {g.items.map(t => (
                        <TxRow key={t.id} t={t}
                          menuOpen={menuFor === t.id}
                          onOpenMenu={() => setMenuFor(menuFor === t.id ? null : t.id)}
                          onEdit={() => openEdit(t)}
                          onDelete={() => { setMenuFor(null); setConfirmDelete(t) }}
                        />
                      ))}
                    </Fragment>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>

      {composer?.kind === 'transaction' && (
        <TransactionComposer
          accounts={accounts} categories={categories} initial={editing}
          onCreate={handleCreate} onUpdate={handleUpdate} onClose={() => setComposer(null)}
          persistedAttachments={editing ? editingAttachments : undefined}
          onUploadDrafts={handleUploadDrafts} onRemovePersistedAttachment={handleRemoveAttachment}
        />
      )}
      {composer?.kind === 'card-tx' && (
        <CardTxComposer
          cards={cards} categories={categories} invoices={invoices} initial={editing}
          onCreate={handleCreate} onUpdate={handleUpdate} onClose={() => setComposer(null)}
          persistedAttachments={editing ? editingAttachments : undefined}
          onUploadDrafts={handleUploadDrafts} onRemovePersistedAttachment={handleRemoveAttachment}
        />
      )}
      {composer?.kind === 'transfer' && (
        <TransferComposer accounts={accounts} categories={categories} onCreate={handleTransfer} onClose={() => setComposer(null)} />
      )}

      {confirmDelete && (
        <DeleteConfirm t={confirmDelete} deleting={deleting}
          onCancel={() => setConfirmDelete(null)} onConfirm={() => doDelete(confirmDelete)} />
      )}

      {toast && (
        <div className="fixed bottom-4 right-4 z-[70] max-w-sm bg-red-600 text-white text-[12px] rounded-lg shadow-lg px-4 py-3">
          {toast}
          <button onClick={() => setToast('')} className="ml-3 underline">fechar</button>
        </div>
      )}
    </AppLayout>
  )
}

function MonthHeader({ ym, first }: { ym: string; first?: boolean }) {
  const [y, m] = ym.split('-')
  return (
    <div className={`px-2 py-2 ${first ? '' : 'mt-3'} text-[10px] uppercase tracking-wider font-semibold text-gray-500 sticky top-0 bg-gray-50 dark:bg-gray-950 z-[1] border-b border-gray-200 dark:border-gray-800`}>
      {MONTH_NAMES[parseInt(m, 10) - 1]} · {y}
    </div>
  )
}

function TxRow({ t, menuOpen, onOpenMenu, onEdit, onDelete }: {
  t: TransactionOut
  menuOpen: boolean
  onOpenMenu: () => void
  onEdit: () => void
  onDelete: () => void
}) {
  const isCard = t.source_type === 'CREDIT_CARD'
  const isIncome = t.amount > 0
  return (
    <tr className="border-t border-gray-100 dark:border-gray-800 hover:bg-gray-50 dark:hover:bg-gray-800/30 transition-colors cursor-pointer" onClick={onEdit}>
      <td className="px-2 py-2 tnum text-gray-400">{fmtDay(t.event_date)}</td>
      <td className="px-2">
        <div className="flex items-center gap-1.5">
          <FILogo slug={t.fi_logo_slug} shortName={t.financial_institution_name ?? '?'} size="sm" />
          <div className="min-w-0">
            <div className="text-[11px] font-medium truncate max-w-[140px] flex items-center gap-1 text-gray-900 dark:text-white">
              {isCard && <CreditCardIcon className="w-3 h-3 text-amber-500 dark:text-amber-400" />}
              {t.account_name ?? t.card_name}
            </div>
            {t.installment_total && <div className="text-[10px] text-gray-500">parc. {t.installment_number}/{t.installment_total}</div>}
          </div>
        </div>
      </td>
      <td className="px-2">
        <div className="flex items-center gap-1.5 text-gray-900 dark:text-white">
          <span>{t.description}</span>
          {t.transfer_group_id && <span className="text-[9px] uppercase tracking-wider px-1 rounded bg-indigo-500/10 text-indigo-600 dark:text-indigo-300">transf.</span>}
          {t.paid_invoice_id && <span className="text-[9px] uppercase tracking-wider px-1 rounded bg-indigo-500/10 text-indigo-600 dark:text-indigo-300">fatura</span>}
        </div>
        {t.notes && <div className="text-[10px] text-gray-500 tnum money">{t.notes}</div>}
      </td>
      <td className="px-2">
        {t.category_name ? (
          <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px]"
            style={{ background: (t.category_color ?? '#6b7280') + '22', color: t.category_color ?? '#6b7280' }}>
            <span className="w-1.5 h-1.5 rounded-full" style={{ background: t.category_color ?? '#6b7280' }} />
            {t.category_name}
          </span>
        ) : (
          <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] bg-gray-100 dark:bg-gray-800/60 text-gray-500 italic">Sem categoria</span>
        )}
      </td>
      <td className={`px-2 text-right tnum money font-medium ${isIncome ? 'text-emerald-500 dark:text-emerald-400' : 'text-gray-900 dark:text-white'}`}>
        {fmtMoney(t.amount, t.currency, { sign: true })}
      </td>
      <td className="px-2 text-center">
        {t.is_reconciled
          ? <Check className="w-3.5 h-3.5 text-emerald-500 mx-auto" aria-label="Reconciliada" />
          : <span className="inline-block w-1.5 h-1.5 rounded-full bg-amber-400" title="Não reconciliada" />}
      </td>
      <td className="px-2 text-gray-500 relative" onClick={e => e.stopPropagation()}>
        <button type="button" onClick={onOpenMenu} aria-label="Ações" className="p-1 rounded hover:bg-gray-100 dark:hover:bg-gray-800">
          <MoreHorizontal className="w-4 h-4" />
        </button>
        {menuOpen && (
          <div className="absolute right-2 top-8 z-20 w-36 rounded-lg border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 shadow-lg py-1 text-[12px]">
            <button type="button" onClick={onEdit} className="w-full text-left px-3 py-1.5 hover:bg-gray-100 dark:hover:bg-gray-800">Editar</button>
            <button type="button" onClick={onDelete} className="w-full text-left px-3 py-1.5 text-red-600 dark:text-red-400 hover:bg-gray-100 dark:hover:bg-gray-800">Excluir</button>
          </div>
        )}
      </td>
    </tr>
  )
}

function DeleteConfirm({ t, deleting, onCancel, onConfirm }: {
  t: TransactionOut
  deleting: boolean
  onCancel: () => void
  onConfirm: () => void
}) {
  const isParent = !!t.installment_total && t.parent_transaction_id === null
  const detail = t.transfer_group_id
    ? 'É uma transferência — as duas pernas (saída e entrada) serão excluídas.'
    : t.paid_invoice_id
      ? 'É o pagamento de uma fatura — ela volta a ficar fechada, sem pagamento.'
      : isParent
        ? `É a 1ª parcela de ${t.installment_total} — todas as parcelas seguintes também serão excluídas.`
        : null
  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/40">
      <div role="dialog" aria-label="Excluir movimentação" className="w-full max-w-sm bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-700 shadow-xl p-6">
        <h2 className="text-base font-semibold text-gray-900 dark:text-white mb-2">Excluir movimentação?</h2>
        <p className="text-sm text-gray-500 dark:text-gray-400">
          {t.description} · {fmtMoney(t.amount, t.currency, { sign: true })}
        </p>
        {detail && <p className="text-[12px] text-amber-600 dark:text-amber-400 mt-2">{detail}</p>}
        <div className="flex justify-end gap-3 mt-5">
          <button onClick={onCancel} className="px-4 py-2 rounded-lg text-sm text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors">Cancelar</button>
          <button onClick={onConfirm} disabled={deleting}
            className="px-4 py-2 rounded-lg bg-red-600 hover:bg-red-500 disabled:opacity-60 text-white text-sm font-medium transition-colors">
            {deleting ? 'Excluindo…' : 'Excluir'}
          </button>
        </div>
      </div>
    </div>
  )
}
