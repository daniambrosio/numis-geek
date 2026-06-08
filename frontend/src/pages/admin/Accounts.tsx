import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Plus, TrendingUp, Wallet } from 'lucide-react'
import { api, type AccountOut, type AssetOut, type FinancialInstitutionOut, type UserOut } from '../../lib/api'
import AppLayout from '../../components/AppLayout'
import { Card, PageHeader, SectionTitle, FILogo, CcyPill, Field, INPUT_CLS } from '../../components/ui'
import { parseDecimal } from '../../lib/parseDecimal'
import { useEscapeKey } from '../../lib/useEscapeKey'

const TYPE_META = {
  investment: { label: 'Investimento', icon: TrendingUp, bg: 'bg-violet-500/15', text: 'text-violet-700 dark:text-violet-300' },
  checking: { label: 'Corrente', icon: Wallet, bg: 'bg-blue-500/15', text: 'text-blue-700 dark:text-blue-300' },
}

function fmtMoney(n: number | null | undefined, currency: string) {
  if (n == null) return '—'
  return n.toLocaleString('pt-BR', { style: 'currency', currency })
}

interface ModalProps {
  initial?: AccountOut
  institutions: FinancialInstitutionOut[]
  onSave: (data: {
    name: string
    account_type: string
    financial_institution_id: string
    currency: string
    opening_balance: number | null
    account_info: string | null
  }) => Promise<void>
  onClose: () => void
}

function Modal({ initial, institutions, onSave, onClose }: ModalProps) {
  const [name, setName] = useState(initial?.name ?? '')
  const [accountType, setAccountType] = useState(initial?.account_type ?? 'checking')
  const [fiId, setFiId] = useState(initial?.financial_institution_id ?? (institutions[0]?.id ?? ''))
  const [currency, setCurrency] = useState(initial?.currency ?? 'BRL')
  const [openingBalance, setOpeningBalance] = useState(initial?.opening_balance?.toString() ?? '')
  const [accountInfo, setAccountInfo] = useState(initial?.account_info ?? '')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    setSaving(true)
    try {
      await onSave({
        name,
        account_type: accountType,
        financial_institution_id: fiId,
        currency,
        opening_balance: accountType === 'checking' && openingBalance !== '' ? parseDecimal(openingBalance) : null,
        account_info: accountInfo.trim() || null,
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
          {initial ? 'Editar Conta' : 'Nova Conta'}
        </h2>
        <form onSubmit={handleSubmit} className="space-y-3">
          <Field label="Nome">
            <input type="text" value={name} onChange={e => setName(e.target.value)} required placeholder="Ex: Itaú Corrente" className={INPUT_CLS} />
          </Field>
          <Field label="Tipo">
            <select value={accountType} onChange={e => setAccountType(e.target.value as 'checking' | 'investment')} className={INPUT_CLS}>
              <option value="checking">Corrente</option>
              <option value="investment">Investimento</option>
            </select>
          </Field>
          <Field label="Instituição">
            <select value={fiId} onChange={e => setFiId(e.target.value)} required className={INPUT_CLS}>
              {institutions.map(fi => <option key={fi.id} value={fi.id}>{fi.short_name}</option>)}
            </select>
          </Field>
          <Field label="Moeda">
            <select value={currency} onChange={e => setCurrency(e.target.value as 'BRL' | 'USD')} className={INPUT_CLS}>
              <option value="BRL">BRL</option>
              <option value="USD">USD</option>
            </select>
          </Field>
          {accountType === 'checking' && (
            <Field label="Saldo de abertura (opcional)">
              <input type="number" step="0.01" value={openingBalance} onChange={e => setOpeningBalance(e.target.value)} placeholder="0,00" className={INPUT_CLS} />
            </Field>
          )}
          <Field label="Informações (opcional)">
            <input type="text" value={accountInfo} onChange={e => setAccountInfo(e.target.value)} placeholder="Agência, número da conta…" className={INPUT_CLS} />
          </Field>

          {error && <p className="text-[12px] text-red-500 dark:text-red-400">{error}</p>}

          <div className="flex justify-end gap-2 pt-2">
            <button type="button" onClick={onClose} className="h-9 px-4 inline-flex items-center rounded-lg text-[12px] text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors">
              Cancelar
            </button>
            <button type="submit" disabled={saving} className="h-9 px-4 inline-flex items-center rounded-lg bg-indigo-500 hover:bg-indigo-400 disabled:opacity-60 text-white text-[12px] font-medium transition-colors">
              {saving ? 'Salvando…' : 'Salvar'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

export default function AdminAccounts() {
  const navigate = useNavigate()
  const [me, setMe] = useState<UserOut | null>(null)
  const [accounts, setAccounts] = useState<AccountOut[]>([])
  const [institutions, setInstitutions] = useState<FinancialInstitutionOut[]>([])
  const [assets, setAssets] = useState<AssetOut[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<AccountOut | undefined>(undefined)
  const [confirmDeactivate, setConfirmDeactivate] = useState<AccountOut | null>(null)
  useEscapeKey(() => { if (confirmDeactivate) setConfirmDeactivate(null); else if (modalOpen) { setModalOpen(false); setEditing(undefined) } })

  useEffect(() => {
    api.me()
      .then(u => {
        if (u.role === 'member') navigate('/dashboard')
        setMe(u)
      })
      .catch(() => navigate('/login'))
  }, [navigate])

  useEffect(() => {
    if (!me) return
    setLoading(true)
    setLoadError('')
    Promise.all([
      api.listAccounts(),
      api.listFinancialInstitutions(),
      api.listAssets({ include_inactive: false }),
    ])
      .then(([accs, fis, as]) => {
        setAccounts(accs)
        setInstitutions(fis)
        setAssets(as)
      })
      .catch(err => setLoadError(err instanceof Error ? err.message : 'Erro ao carregar.'))
      .finally(() => setLoading(false))
  }, [me])

  const fiById = useMemo(() => {
    const m = new Map<string, FinancialInstitutionOut>()
    for (const fi of institutions) m.set(fi.id, fi)
    return m
  }, [institutions])

  const assetCountByFi = useMemo(() => {
    const m = new Map<string, number>()
    for (const a of assets) {
      m.set(a.financial_institution_id, (m.get(a.financial_institution_id) ?? 0) + 1)
    }
    return m
  }, [assets])

  const grouped = useMemo(() => ({
    investment: accounts.filter(a => a.account_type === 'investment'),
    checking: accounts.filter(a => a.account_type === 'checking'),
  }), [accounts])

  const stats = useMemo(() => {
    const types = new Set(accounts.map(a => a.account_type)).size
    const fis = new Set(accounts.map(a => a.financial_institution_id)).size
    return { types, fis }
  }, [accounts])

  async function handleSave(data: Parameters<typeof api.createAccount>[0]) {
    if (editing) {
      const updated = await api.updateAccount(editing.id, data)
      setAccounts(prev => prev.map(a => a.id === updated.id ? updated : a))
    } else {
      const created = await api.createAccount(data)
      setAccounts(prev => [...prev, created].sort((a, b) => a.name.localeCompare(b.name)))
    }
  }

  async function handleDeactivate(account: AccountOut) {
    await api.deactivateAccount(account.id)
    setAccounts(prev => prev.filter(a => a.id !== account.id))
    setConfirmDeactivate(null)
  }

  if (!me) return null

  const sections: Array<{ key: 'investment' | 'checking'; rows: AccountOut[] }> = [
    { key: 'investment', rows: grouped.investment },
    { key: 'checking', rows: grouped.checking },
  ]

  return (
    <AppLayout user={me}>
      <div className="space-y-6">
        <PageHeader
          title="Contas"
          count={accounts.length}
          countLabel={`contas · ${stats.types} ${stats.types === 1 ? 'tipo' : 'tipos'} · ${stats.fis} ${stats.fis === 1 ? 'instituição' : 'instituições'}`}
          action={
            <button
              onClick={() => { setEditing(undefined); setModalOpen(true) }}
              className="h-8 px-3 inline-flex items-center gap-1.5 rounded-lg text-[12px] bg-indigo-500 hover:bg-indigo-400 text-white transition-colors"
            >
              <Plus className="w-3.5 h-3.5" /> Nova Conta
            </button>
          }
        />

        {loadError ? (
          <Card>
            <div className="text-sm text-red-600 dark:text-red-400 text-center py-6">{loadError}</div>
          </Card>
        ) : loading ? (
          <Card>
            <div className="text-sm text-gray-400 dark:text-gray-600 text-center py-12">Carregando…</div>
          </Card>
        ) : (
          sections.map(({ key, rows }) => {
            const meta = TYPE_META[key]
            const Icon = meta.icon
            return (
              <Card key={key}>
                <SectionTitle action={<span className="text-[11px] text-gray-500">{rows.length}</span>}>
                  <span className="flex items-center gap-2">
                    <Icon className={`w-3.5 h-3.5 ${meta.text}`} />
                    {key === 'investment' ? 'Contas de investimento' : 'Contas correntes'}
                  </span>
                </SectionTitle>
                {rows.length === 0 ? (
                  <div className="text-[11px] text-gray-400 dark:text-gray-600 text-center py-6">
                    Nenhuma {key === 'investment' ? 'conta de investimento' : 'conta corrente'}.
                  </div>
                ) : (
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                    {rows.map(acc => {
                      const fi = fiById.get(acc.financial_institution_id)
                      const assetCount = acc.account_type === 'investment' ? (assetCountByFi.get(acc.financial_institution_id) ?? 0) : 0
                      return (
                        <div
                          key={acc.id}
                          role="button"
                          tabIndex={0}
                          onClick={() => { setEditing(acc); setModalOpen(true) }}
                          onKeyDown={(e) => { if (e.key === 'Enter') { setEditing(acc); setModalOpen(true) } }}
                          className="flex items-center gap-3 p-2.5 -mx-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800/40 transition-colors text-left w-full cursor-pointer"
                        >
                          <FILogo slug={fi?.logo_slug ?? null} shortName={fi?.short_name ?? '··'} size="md" />
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2 flex-wrap">
                              <span className="text-[13px] font-medium text-gray-900 dark:text-white">{acc.name}</span>
                              <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded-md text-[10px] font-medium uppercase tracking-wider ${meta.bg} ${meta.text}`}>
                                <Icon className="w-3 h-3" /> {meta.label}
                              </span>
                              <CcyPill ccy={acc.currency} />
                            </div>
                            <div className="text-[11px] text-gray-500 dark:text-gray-400 mt-0.5 flex items-center gap-2">
                              <span>{fi?.short_name ?? '—'}</span>
                              {assetCount > 0 && (
                                <>
                                  <span>·</span>
                                  <span>{assetCount} ativo{assetCount === 1 ? '' : 's'}</span>
                                </>
                              )}
                              {acc.account_info && (
                                <>
                                  <span>·</span>
                                  <span className="truncate">{acc.account_info}</span>
                                </>
                              )}
                            </div>
                          </div>
                          <div className="text-right shrink-0">
                            <div className="text-[10px] uppercase tracking-wider text-gray-500 dark:text-gray-400">Saldo</div>
                            <div className={`text-[13px] font-semibold tnum money ${acc.opening_balance == null ? 'text-gray-400 dark:text-gray-600' : 'text-gray-900 dark:text-white'}`}>
                              {fmtMoney(acc.opening_balance, acc.currency)}
                            </div>
                          </div>
                          <button
                            type="button"
                            onClick={(e) => { e.stopPropagation(); setConfirmDeactivate(acc) }}
                            className="text-[10px] px-2 py-1 rounded text-red-500 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors shrink-0"
                            title="Desativar"
                          >
                            ×
                          </button>
                        </div>
                      )
                    })}
                  </div>
                )}
              </Card>
            )
          })
        )}
      </div>

      {modalOpen && institutions.length > 0 && (
        <Modal
          initial={editing}
          institutions={institutions}
          onSave={handleSave}
          onClose={() => { setModalOpen(false); setEditing(undefined) }}
        />
      )}

      {confirmDeactivate && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/40">
          <div className="w-full max-w-sm bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-700 shadow-xl p-6">
            <h2 className="text-base font-semibold text-gray-900 dark:text-white mb-2">Desativar conta?</h2>
            <p className="text-sm text-gray-500 dark:text-gray-400 mb-6">
              <strong>{confirmDeactivate.name}</strong> será desativada.
            </p>
            <div className="flex justify-end gap-3">
              <button onClick={() => setConfirmDeactivate(null)} className="px-4 py-2 rounded-lg text-sm text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors">
                Cancelar
              </button>
              <button onClick={() => handleDeactivate(confirmDeactivate)} className="px-4 py-2 rounded-lg bg-red-600 hover:bg-red-700 text-white text-sm font-medium transition-colors">
                Desativar
              </button>
            </div>
          </div>
        </div>
      )}
    </AppLayout>
  )
}
