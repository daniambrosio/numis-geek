/* Spec 70 fase 3 — Detalhe da conta corrente (/accounts/:id), fiel ao proto
 * ContaDetail + ContaCheckingBody (index.html:3494-3640): header com logo,
 * nome, CcyPill, instituição · tipo e ações (Reconciliar, Movimentação);
 * card hero com Saldo atual (+ BRL quando USD, Trend MoM) e sparkline dos
 * últimos 6 meses; 3 KpiTiles (Entradas / Saídas / Resultado · mês);
 * tabela de Movimentações da conta.
 *
 * Deltas declarados na spec 70:
 * - o card "Orçamento" do proto fica de fora (spec futura de budget); no lugar
 *   dele entra "Saldo de abertura e vínculo" (fase 2 da spec 80);
 * - card novo "Conferência com os fechamentos": digitado × derivado × diferença
 *   mês a mês — fechamento CLOSED nunca é sobrescrito, a decisão é do user;
 * - conta de investimento: só o header (o detalhe dela é o de Ativos).
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { FileText, Link2, Loader2, Pencil, Plus } from 'lucide-react'
import {
  api, type AccountDetailOut, type AssetOut, type BalanceCheckRow, type CategoryOut,
  type TransactionCreatePayload, type TransactionOut, type TransactionUpdatePayload, type UserOut,
} from '../lib/api'
import AppLayout from '../components/AppLayout'
import { Card, CcyPill, FILogo, Field, INPUT_CLS, SectionTitle, Trend } from '../components/ui'
import KpiTile from '../components/KpiTile'
import Sparkline from '../components/Sparkline'
import { TransactionComposer, fmtMoney } from '../components/TransactionComposers'
import { fmtBRL } from '../lib/money'
import { parseDecimal } from '../lib/parseDecimal'
import { useEscapeKey } from '../lib/useEscapeKey'

const ACCOUNT_TYPE_LABEL: Record<string, string> = { checking: 'Conta corrente', investment: 'Conta investimento' }
const STATUS_LABEL: Record<BalanceCheckRow['status'], string> = { OPEN: 'Aberto', IN_REVIEW: 'Em revisão', CLOSED: 'Fechado' }

function fmtDay(iso: string) {
  const [y, m, d] = iso.split('-')
  return `${d}/${m}/${y.slice(2)}`
}

function fmtMonth(iso: string) {
  const [y, m] = iso.split('-')
  return `${m}/${y}`
}

/** MoM do saldo: último ponto × penúltimo da série (null se não dá pra calcular). */
export function momChange(series: { balance: number }[]): number | null {
  if (series.length < 2) return null
  const prev = series[series.length - 2].balance
  const last = series[series.length - 1].balance
  if (!prev) return null
  return (last - prev) / Math.abs(prev)
}

export default function AccountDetail() {
  const navigate = useNavigate()
  const { id } = useParams<{ id: string }>()
  const [me, setMe] = useState<UserOut | null>(null)
  const [acc, setAcc] = useState<AccountDetailOut | null>(null)
  const [txs, setTxs] = useState<TransactionOut[]>([])
  const [check, setCheck] = useState<BalanceCheckRow[]>([])
  const [categories, setCategories] = useState<CategoryOut[]>([])
  const [cashAssets, setCashAssets] = useState<AssetOut[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [composer, setComposer] = useState<{ editing?: TransactionOut } | null>(null)
  const [editingOpening, setEditingOpening] = useState(false)
  const [editingLink, setEditingLink] = useState(false)
  const [togglingSource, setTogglingSource] = useState(false)
  const [sourceError, setSourceError] = useState('')

  useEscapeKey(() => {
    if (editingOpening) setEditingOpening(false)
    else if (editingLink) setEditingLink(false)
  })

  useEffect(() => {
    api.me().then(setMe).catch(() => navigate('/login'))
  }, [navigate])

  const reload = useCallback(async () => {
    if (!id) return
    const detail = await api.getAccount(id)
    setAcc(detail)
    if (detail.account_type === 'checking') {
      const [list, rows] = await Promise.all([
        api.listTransactions({ account_id: [id] }),
        api.accountBalanceCheck(id),
      ])
      setTxs(list.items)
      setCheck(rows)
    }
  }, [id])

  useEffect(() => {
    if (!me) return
    setLoadError('')
    reload()
      .catch(err => setLoadError(err instanceof Error ? err.message : 'Erro ao carregar.'))
      .finally(() => setLoading(false))
  }, [me, reload])

  async function toggleSource() {
    if (!acc) return
    setTogglingSource(true)
    setSourceError('')
    try {
      setAcc(await api.updateBalanceSource(acc.id, !acc.balance_from_ledger))
      await reload()
    } catch (err) {
      setSourceError(err instanceof Error ? err.message : 'Erro ao salvar.')
    } finally {
      setTogglingSource(false)
    }
  }

  // Cadastros auxiliares — falha não derruba a página.
  useEffect(() => {
    if (!me) return
    api.listCategories().then(setCategories).catch(() => {})
    api.listAssets({ asset_class: 'CASH' }).then(setCashAssets).catch(() => {})
  }, [me])

  const isAdmin = me?.role === 'admin' || me?.role === 'sysadmin'
  const series = useMemo(() => acc?.balance_series.map(p => p.balance) ?? [], [acc])
  const mom = useMemo(() => momChange(acc?.balance_series ?? []), [acc])

  if (!me) return null

  return (
    <AppLayout user={me}>
      <div className="space-y-6">
        {loadError ? (
          <Card><div className="text-sm text-red-600 dark:text-red-400 text-center py-6">{loadError}</div></Card>
        ) : loading || !acc ? (
          <Card><div className="text-sm text-gray-400 dark:text-gray-600 text-center py-12">Carregando…</div></Card>
        ) : (
          <>
            <Card padding="p-6">
              <div className="flex items-start gap-4">
                <FILogo slug={acc.fi_logo_slug} shortName={acc.financial_institution_name} size="lg" />
                <div className="flex-1">
                  <div className="flex items-center gap-2">
                    <h1 className="text-2xl font-semibold text-gray-900 dark:text-white">{acc.name}</h1>
                    <CcyPill ccy={acc.currency} />
                  </div>
                  <div className="text-[13px] text-gray-500 mt-0.5 flex items-center gap-2">
                    <span>{acc.fi_long_name ?? acc.financial_institution_name}</span>
                    <span>·</span>
                    <span>{ACCOUNT_TYPE_LABEL[acc.account_type]}</span>
                  </div>
                </div>
                {acc.account_type === 'checking' && (
                  <div className="flex items-center gap-2">
                    <button disabled title="Chega com o import de extrato (spec 71)"
                      className="h-8 px-3 inline-flex items-center gap-1.5 rounded-lg text-[12px] bg-gray-100 dark:bg-gray-800 text-gray-400 dark:text-gray-600 cursor-not-allowed">
                      <FileText className="w-3.5 h-3.5" /> Reconciliar
                    </button>
                    <button onClick={() => setComposer({})}
                      className="h-8 px-3 inline-flex items-center gap-1.5 rounded-lg text-[12px] bg-indigo-500 hover:bg-indigo-400 text-white transition-colors">
                      <Plus className="w-3.5 h-3.5" /> Movimentação
                    </button>
                  </div>
                )}
              </div>
            </Card>

            {acc.account_type === 'investment' ? (
              <Card>
                <div className="text-[12px] text-gray-500 text-center py-8">
                  Conta de investimento — as posições estão em <Link to="/assets" className="text-indigo-500 hover:text-indigo-400">Ativos</Link>.
                </div>
              </Card>
            ) : (
              <>
                <div className="grid grid-cols-12 gap-6">
                  <Card className="col-span-12 lg:col-span-8">
                    <div className="flex items-baseline justify-between gap-6">
                      <div>
                        <div className="text-[11px] uppercase tracking-wider text-gray-500">Saldo atual</div>
                        <div className="text-3xl font-semibold tnum money mt-1 text-gray-900 dark:text-white" data-testid="account-balance">
                          {fmtMoney(acc.balance ?? 0, acc.currency)}
                        </div>
                        <div className="mt-1 flex items-center gap-2 text-[11px] text-gray-500">
                          {acc.currency === 'USD' && acc.balance_brl != null && (
                            <><span className="tnum money">{fmtBRL(acc.balance_brl)}</span><span>·</span></>
                          )}
                          <span>derivado das movimentações</span>
                          {mom != null && <><span>·</span><Trend value={mom} suffix="MoM" /></>}
                        </div>
                      </div>
                      <div className="w-[200px]">
                        <Sparkline data={series} w={200} h={48} color="#3b82f6" />
                        <div className="text-right text-[10px] text-gray-500 uppercase tracking-wider mt-1">últimos 6 meses</div>
                      </div>
                    </div>
                    <div className="mt-5 grid grid-cols-3 gap-3">
                      <KpiTile label="Entradas · mês" value={fmtMoney(acc.month?.inflows ?? 0, acc.currency)} intent="positive" />
                      <KpiTile label="Saídas · mês" value={fmtMoney(acc.month?.outflows ?? 0, acc.currency)} intent="negative" />
                      <KpiTile label="Resultado · mês" value={fmtMoney(acc.month?.net ?? 0, acc.currency, { sign: true })} />
                    </div>
                  </Card>

                  <Card className="col-span-12 lg:col-span-4">
                    <SectionTitle>Saldo de abertura e vínculo</SectionTitle>
                    <div className="space-y-3 text-[12px]">
                      <div className="flex items-start justify-between gap-2">
                        <div>
                          <div className="text-gray-500">Saldo de abertura</div>
                          <div className="text-[13px] font-medium tnum money text-gray-900 dark:text-white" data-testid="opening-balance">
                            {acc.opening_balance != null ? fmtMoney(acc.opening_balance, acc.currency) : '—'}
                          </div>
                          <div className="text-[11px] text-gray-500">
                            {acc.opening_balance_date ? `em ${fmtDay(acc.opening_balance_date)} · soma movimentações depois dessa data` : 'sem data — soma todas as movimentações'}
                          </div>
                        </div>
                        {isAdmin && (
                          <button onClick={() => setEditingOpening(true)} aria-label="Editar saldo de abertura"
                            className="h-7 px-2 inline-flex items-center gap-1 rounded-md text-[11px] bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700">
                            <Pencil className="w-3 h-3" /> Editar
                          </button>
                        )}
                      </div>
                      <div className="flex items-start justify-between gap-2 pt-3 border-t border-gray-100 dark:border-gray-800">
                        <div>
                          <div className="text-gray-500">Ativo no fechamento</div>
                          <div className="text-[13px] font-medium text-gray-900 dark:text-white" data-testid="linked-asset">
                            {acc.linked_asset ? (
                              <Link to={`/assets/${acc.linked_asset.id}`} className="hover:text-indigo-500">{acc.linked_asset.name}</Link>
                            ) : 'Nenhum'}
                          </div>
                          <div className="text-[11px] text-gray-500">
                            {acc.linked_asset ? 'espelha esta conta nos fechamentos' : 'sem vínculo, a conta não entra nos fechamentos'}
                          </div>
                        </div>
                        {isAdmin && (
                          <button onClick={() => setEditingLink(true)} aria-label="Alterar vínculo"
                            className="h-7 px-2 inline-flex items-center gap-1 rounded-md text-[11px] bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700">
                            <Link2 className="w-3 h-3" /> Alterar
                          </button>
                        )}
                      </div>
                      <div className="flex items-start justify-between gap-2 pt-3 border-t border-gray-100 dark:border-gray-800">
                        <div>
                          <div className="text-gray-500">Saldo no fechamento</div>
                          <div className="text-[13px] font-medium text-gray-900 dark:text-white" data-testid="balance-source">
                            {acc.balance_from_ledger ? 'Vem das movimentações' : 'Digitado no fechamento'}
                          </div>
                          <div className="text-[11px] text-gray-500">
                            {acc.balance_from_ledger
                              ? 'fechamentos abertos usam o saldo calculado; fechados não mudam'
                              : 'ligue quando a conferência abaixo bater'}
                          </div>
                          {sourceError && <div className="text-[11px] text-red-600 dark:text-red-400 mt-1">{sourceError}</div>}
                        </div>
                        {isAdmin && (
                          <button onClick={toggleSource}
                            disabled={togglingSource || (!acc.balance_from_ledger && (!acc.linked_asset || !acc.opening_balance_date))}
                            title={!acc.balance_from_ledger && (!acc.linked_asset || !acc.opening_balance_date) ? 'Precisa de ativo vinculado e data de abertura' : undefined}
                            aria-label={acc.balance_from_ledger ? 'Desligar saldo pelas movimentações' : 'Ligar saldo pelas movimentações'}
                            className="h-7 px-2 inline-flex items-center gap-1 rounded-md text-[11px] bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700 disabled:opacity-50 disabled:cursor-not-allowed">
                            {togglingSource && <Loader2 className="w-3 h-3 animate-spin" />}
                            {acc.balance_from_ledger ? 'Desligar' : 'Ligar'}
                          </button>
                        )}
                      </div>
                    </div>
                  </Card>
                </div>

                <Card>
                  <SectionTitle>Conferência com os fechamentos</SectionTitle>
                  {check.length === 0 ? (
                    <div className="text-[12px] text-gray-400 dark:text-gray-600 text-center py-6">
                      {acc.linked_asset && acc.opening_balance_date
                        ? 'Nenhum fechamento desde o saldo de abertura.'
                        : 'A conferência aparece quando a conta tem ativo vinculado e data de abertura.'}
                    </div>
                  ) : (
                    <table className="w-full text-[12px]" data-testid="balance-check">
                      <thead>
                        <tr className="text-[10px] uppercase tracking-wider text-gray-500">
                          <th className="text-left font-medium px-2 py-2">Fechamento</th>
                          <th className="text-left font-medium px-2 py-2">Status</th>
                          <th className="text-right font-medium px-2 py-2">No fechamento</th>
                          <th className="text-right font-medium px-2 py-2">Pelas movimentações</th>
                          <th className="text-right font-medium px-2 py-2">Diferença</th>
                        </tr>
                      </thead>
                      <tbody>
                        {check.map(r => {
                          const off = r.difference != null && Math.abs(r.difference) >= 0.01
                          return (
                            <tr key={r.snapshot_id} className="border-t border-gray-100 dark:border-gray-800">
                              <td className="px-2 py-2">
                                <Link to={`/snapshots/${r.period_end_date.slice(0, 7)}`} className="hover:text-indigo-500">{fmtMonth(r.period_end_date)}</Link>
                              </td>
                              <td className="px-2 text-gray-500">{STATUS_LABEL[r.status]}</td>
                              <td className="px-2 text-right tnum money">{r.typed != null ? fmtMoney(r.typed, acc.currency) : '—'}</td>
                              <td className="px-2 text-right tnum money">{fmtMoney(r.derived, acc.currency)}</td>
                              <td className={`px-2 text-right tnum money font-medium ${off ? 'text-amber-600 dark:text-amber-400' : 'text-emerald-600 dark:text-emerald-400'}`}>
                                {r.difference == null ? '—' : off ? fmtMoney(r.difference, acc.currency, { sign: true }) : 'confere'}
                              </td>
                            </tr>
                          )
                        })}
                      </tbody>
                    </table>
                  )}
                  {check.some(r => r.status === 'CLOSED' && r.difference != null && Math.abs(r.difference) >= 0.01) && (
                    <div className="mt-3 text-[11px] text-gray-500">
                      Fechamento fechado não é recalculado sozinho — a diferença fica registrada aqui e o ajuste é decisão sua, mês a mês.
                    </div>
                  )}
                </Card>

                <Card>
                  <SectionTitle>Movimentações</SectionTitle>
                  {txs.length === 0 ? (
                    <div className="text-[12px] text-gray-400 dark:text-gray-600 text-center py-8">Nenhuma movimentação nesta conta.</div>
                  ) : (
                    <div className="overflow-x-auto -mx-2">
                      <table className="w-full text-[12px]">
                        <thead>
                          <tr className="text-[10px] uppercase tracking-wider text-gray-500">
                            <th className="text-left font-medium px-2 py-2">Data</th>
                            <th className="text-left font-medium px-2 py-2">Descrição</th>
                            <th className="text-left font-medium px-2 py-2">Categoria</th>
                            <th className="text-right font-medium px-2 py-2">Valor</th>
                          </tr>
                        </thead>
                        <tbody>
                          {txs.map(t => (
                            <tr key={t.id} onClick={() => setComposer({ editing: t })}
                              className="border-t border-gray-100 dark:border-gray-800 hover:bg-gray-50 dark:hover:bg-gray-800/30 cursor-pointer">
                              <td className="px-2 py-2 tnum text-gray-400">{fmtDay(t.event_date)}</td>
                              <td className="px-2 text-gray-900 dark:text-white">{t.description}</td>
                              <td className="px-2">
                                {t.category_name ? (
                                  <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px]"
                                    style={{ background: (t.category_color ?? '#6b7280') + '22', color: t.category_color ?? '#6b7280' }}>
                                    {t.category_name}
                                  </span>
                                ) : <span className="text-[10px] italic text-gray-500">Sem categoria</span>}
                              </td>
                              <td className={`px-2 text-right tnum money font-medium ${t.amount > 0 ? 'text-emerald-500 dark:text-emerald-400' : 'text-gray-900 dark:text-white'}`}>
                                {fmtMoney(t.amount, t.currency, { sign: true })}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </Card>
              </>
            )}
          </>
        )}
      </div>

      {composer && acc && (
        <TransactionComposer
          accounts={[acc]} categories={categories} initial={composer.editing}
          onCreate={async (data: TransactionCreatePayload) => { const r = await api.createTransaction(data); await reload(); return r }}
          onUpdate={async (txId: string, data: TransactionUpdatePayload) => { const r = await api.updateTransaction(txId, data); await reload(); return r }}
          onClose={() => setComposer(null)}
        />
      )}

      {editingOpening && acc && (
        <OpeningBalanceModal
          acc={acc}
          onSave={async data => { setAcc(await api.updateOpeningBalance(acc.id, data)); await reload() }}
          onClose={() => setEditingOpening(false)}
        />
      )}

      {editingLink && acc && (
        <LinkAssetModal
          acc={acc}
          cashAssets={cashAssets}
          onSave={async assetId => { setAcc(await api.setLinkedAsset(acc.id, assetId)); await reload() }}
          onClose={() => setEditingLink(false)}
        />
      )}
    </AppLayout>
  )
}

function ModalShell({ title, label, children }: { title: string; label: string; children: React.ReactNode }) {
  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/40">
      <div role="dialog" aria-label={label} className="w-full max-w-sm bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-700 shadow-xl p-6">
        <h2 className="text-base font-semibold text-gray-900 dark:text-white mb-2">{title}</h2>
        {children}
      </div>
    </div>
  )
}

function OpeningBalanceModal({ acc, onSave, onClose }: {
  acc: AccountDetailOut
  onSave: (data: { opening_balance: number | null; opening_balance_date: string | null }) => Promise<void>
  onClose: () => void
}) {
  const [value, setValue] = useState(acc.opening_balance != null ? String(acc.opening_balance).replace('.', ',') : '')
  const [day, setDay] = useState(acc.opening_balance_date ?? '')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const parsed = value.trim() === '' ? null : parseDecimal(value)
  const valid = (parsed === null && value.trim() === '') || (parsed !== null && day !== '')

  async function submit() {
    setSaving(true)
    setError('')
    try {
      await onSave({ opening_balance: parsed, opening_balance_date: day || null })
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Erro ao salvar.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <ModalShell title="Saldo de abertura" label="Saldo de abertura">
      <p className="text-sm text-gray-500 dark:text-gray-400 mb-4">
        O saldo do dia anterior ao extrato mais antigo que você importar. Movimentações até essa data não somam.
      </p>
      <div className="space-y-3">
        <Field label={`Saldo · ${acc.currency}`}>
          <input type="text" value={value} onChange={e => setValue(e.target.value)} placeholder="0,00" className={INPUT_CLS} aria-label="Saldo de abertura" />
        </Field>
        <Field label="Em">
          <input type="date" value={day} onChange={e => setDay(e.target.value)} className={INPUT_CLS} aria-label="Data do saldo de abertura" />
        </Field>
      </div>
      {!valid && <p className="text-[12px] text-amber-600 dark:text-amber-400 mt-3">Informe a data do saldo de abertura.</p>}
      {error && <p className="text-[12px] text-red-500 dark:text-red-400 mt-3">{error}</p>}
      <div className="flex justify-end gap-3 mt-5">
        <button onClick={onClose} className="px-4 py-2 rounded-lg text-sm text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors">Cancelar</button>
        <button disabled={!valid || saving} onClick={submit}
          className="px-4 py-2 rounded-lg bg-indigo-500 hover:bg-indigo-400 disabled:opacity-60 text-white text-sm font-medium transition-colors">
          {saving ? 'Salvando…' : 'Salvar'}
        </button>
      </div>
    </ModalShell>
  )
}

function LinkAssetModal({ acc, cashAssets, onSave, onClose }: {
  acc: AccountDetailOut
  cashAssets: AssetOut[]
  onSave: (assetId: string | null) => Promise<void>
  onClose: () => void
}) {
  // Só CASH livre (ou o atual) e na moeda da conta.
  const options = cashAssets.filter(a =>
    a.currency === acc.currency && (!a.linked_account_id || a.linked_account_id === acc.id),
  )
  const [assetId, setAssetId] = useState(acc.linked_asset?.id ?? '')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  async function submit() {
    setSaving(true)
    setError('')
    try {
      await onSave(assetId || null)
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Erro ao salvar.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <ModalShell title="Ativo no fechamento" label="Ativo no fechamento">
      <p className="text-sm text-gray-500 dark:text-gray-400 mb-4">
        O ativo CASH que representa esta conta nos fechamentos. Fechamentos abertos passam a usar o saldo calculado; os fechados não mudam.
      </p>
      <Field label="Ativo CASH">
        <select value={assetId} onChange={e => setAssetId(e.target.value)} className={INPUT_CLS} aria-label="Ativo CASH">
          <option value="">Sem vínculo</option>
          {options.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}
        </select>
      </Field>
      {error && <p className="text-[12px] text-red-500 dark:text-red-400 mt-3">{error}</p>}
      <div className="flex justify-end gap-3 mt-5">
        <button onClick={onClose} className="px-4 py-2 rounded-lg text-sm text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors">Cancelar</button>
        <button disabled={saving} onClick={submit}
          className="px-4 py-2 rounded-lg bg-indigo-500 hover:bg-indigo-400 disabled:opacity-60 text-white text-sm font-medium transition-colors">
          {saving ? 'Salvando…' : 'Salvar'}
        </button>
      </div>
    </ModalShell>
  )
}
