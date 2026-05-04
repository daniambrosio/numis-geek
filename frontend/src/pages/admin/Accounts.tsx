import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, type AccountOut, type CustodianGroupOut, type FinancialInstitutionOut, type UserOut } from '../../lib/api'
import AppLayout from '../../components/AppLayout'

function accountTypeLabel(t: string) {
  return t === 'checking' ? 'Corrente' : 'Investimento'
}

function accountTypeBadge(t: string) {
  return t === 'checking'
    ? 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400'
    : 'bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400'
}

function currencyBadge(c: string) {
  return c === 'USD'
    ? 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400'
    : 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400'
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
        opening_balance: accountType === 'checking' && openingBalance !== '' ? parseFloat(openingBalance) : null,
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
      <div className="w-full max-w-md bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-700 shadow-xl p-6">
        <h2 className="text-base font-semibold text-gray-900 dark:text-white mb-5">
          {initial ? 'Editar Conta' : 'Nova Conta'}
        </h2>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm text-gray-700 dark:text-gray-300 mb-1">Nome</label>
            <input
              type="text"
              value={name}
              onChange={e => setName(e.target.value)}
              required
              placeholder="Ex: Itaú Corrente"
              className="w-full px-3.5 py-2 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
          </div>

          <div>
            <label className="block text-sm text-gray-700 dark:text-gray-300 mb-1">Tipo</label>
            <select
              value={accountType}
              onChange={e => setAccountType(e.target.value as 'checking' | 'investment')}
              className="w-full px-3.5 py-2 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
            >
              <option value="checking">Corrente</option>
              <option value="investment">Investimento</option>
            </select>
          </div>

          <div>
            <label className="block text-sm text-gray-700 dark:text-gray-300 mb-1">Instituição Financeira</label>
            <select
              value={fiId}
              onChange={e => setFiId(e.target.value)}
              required
              className="w-full px-3.5 py-2 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
            >
              {institutions.map(fi => (
                <option key={fi.id} value={fi.id}>{fi.short_name}</option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-sm text-gray-700 dark:text-gray-300 mb-1">Moeda</label>
            <select
              value={currency}
              onChange={e => setCurrency(e.target.value as 'BRL' | 'USD')}
              className="w-full px-3.5 py-2 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
            >
              <option value="BRL">BRL</option>
              <option value="USD">USD</option>
            </select>
          </div>

          {accountType === 'checking' && (
            <div>
              <label className="block text-sm text-gray-700 dark:text-gray-300 mb-1">Saldo de abertura (opcional)</label>
              <input
                type="number"
                step="0.01"
                value={openingBalance}
                onChange={e => setOpeningBalance(e.target.value)}
                placeholder="0.00"
                className="w-full px-3.5 py-2 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
              />
            </div>
          )}

          <div>
            <label className="block text-sm text-gray-700 dark:text-gray-300 mb-1">Informações da conta (opcional)</label>
            <input
              type="text"
              value={accountInfo}
              onChange={e => setAccountInfo(e.target.value)}
              placeholder="Agência, número da conta ou código da corretora"
              className="w-full px-3.5 py-2 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
          </div>

          {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}

          <div className="flex justify-end gap-3 pt-2">
            <button type="button" onClick={onClose} className="px-4 py-2 rounded-lg text-sm text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors">
              Cancelar
            </button>
            <button type="submit" disabled={saving} className="px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-700 disabled:opacity-60 text-white text-sm font-medium transition-colors">
              {saving ? 'Salvando…' : 'Salvar'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

type Tab = 'contas' | 'ativos'

function ByCustodianView({ groups, loading, loadError }: { groups: CustodianGroupOut[]; loading: boolean; loadError: string }) {
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({})
  // Auto-expand if only one group
  const autoExpand = groups.length === 1
  function isCollapsed(id: string) {
    if (autoExpand) return false
    return collapsed[id] ?? false
  }
  function toggle(id: string) {
    setCollapsed(prev => ({ ...prev, [id]: !prev[id] }))
  }

  if (loading) {
    return <div className="p-12 text-center text-sm text-gray-400 dark:text-gray-600">Carregando…</div>
  }
  if (loadError) {
    return <div className="p-12 text-center text-sm text-red-500">{loadError}</div>
  }
  if (groups.length === 0) {
    return (
      <div className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-800 p-12 text-center text-sm text-gray-400 dark:text-gray-600">
        Nenhum custodiante com contas de investimento ou ativos.
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {groups.map(g => {
        const fi = g.financial_institution
        const collapsedNow = isCollapsed(fi.id)
        return (
          <div key={fi.id} className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-800 overflow-hidden">
            <button
              onClick={() => toggle(fi.id)}
              disabled={autoExpand}
              className="w-full flex items-center justify-between px-5 py-4 hover:bg-gray-50 dark:hover:bg-gray-800/40 transition-colors"
            >
              <div className="flex items-center gap-3">
                {fi.logo_slug ? (
                  <img
                    src={`https://www.google.com/s2/favicons?sz=64&domain=${fi.logo_slug}.com.br`}
                    onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = 'none' }}
                    alt=""
                    className="w-8 h-8 rounded"
                  />
                ) : (
                  <div className="w-8 h-8 rounded bg-gray-100 dark:bg-gray-800" />
                )}
                <div className="text-left">
                  <p className="font-medium text-gray-900 dark:text-white text-sm">{fi.short_name}</p>
                  <p className="text-xs text-gray-500 dark:text-gray-400">
                    {g.assets.length} ativo{g.assets.length === 1 ? '' : 's'} · {g.accounts.length} conta{g.accounts.length === 1 ? '' : 's'} de investimento
                  </p>
                </div>
              </div>
              {!autoExpand && (
                <span className="text-gray-400 text-sm">{collapsedNow ? '▸' : '▾'}</span>
              )}
            </button>

            {!collapsedNow && (
              <div className="border-t border-gray-100 dark:border-gray-800">
                {g.accounts.length > 0 && (
                  <div className="px-5 py-3 border-b border-gray-100 dark:border-gray-800">
                    <p className="text-xs uppercase tracking-wide text-gray-400 dark:text-gray-500 mb-2">Contas</p>
                    <ul className="space-y-1">
                      {g.accounts.map(a => (
                        <li key={a.id} className="flex items-center justify-between text-sm">
                          <span className="text-gray-700 dark:text-gray-300">{a.name}</span>
                          <span className="text-xs text-gray-400">{a.currency}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                <div className="px-5 py-3">
                  <p className="text-xs uppercase tracking-wide text-gray-400 dark:text-gray-500 mb-2">Ativos</p>
                  {g.assets.length === 0 ? (
                    <p className="text-sm text-gray-400 dark:text-gray-600 italic">Nenhum ativo cadastrado neste custodiante.</p>
                  ) : (
                    <ul className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-1.5">
                      {g.assets.map(a => (
                        <li key={a.id}>
                          <Link
                            to={`/assets`}
                            className="flex items-center gap-2 px-2 py-1.5 rounded hover:bg-gray-50 dark:hover:bg-gray-800/50 transition-colors text-sm"
                          >
                            {a.ticker && (
                              <span className="font-mono text-xs text-gray-500 dark:text-gray-400 w-16 truncate">{a.ticker}</span>
                            )}
                            <span className="text-gray-900 dark:text-white truncate flex-1">{a.name}</span>
                            <span className="text-[10px] text-gray-400 uppercase">{a.currency}</span>
                          </Link>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

export default function AdminAccounts() {
  const navigate = useNavigate()
  const [me, setMe] = useState<UserOut | null>(null)
  const [accounts, setAccounts] = useState<AccountOut[]>([])
  const [institutions, setInstitutions] = useState<FinancialInstitutionOut[]>([])
  const [byCustodian, setByCustodian] = useState<CustodianGroupOut[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<AccountOut | undefined>(undefined)
  const [confirmDeactivate, setConfirmDeactivate] = useState<AccountOut | null>(null)
  const [tab, setTab] = useState<Tab>(() => (localStorage.getItem('accounts-tab') as Tab) || 'contas')

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
      api.listAccountsByCustodian(),
    ])
      .then(([accs, fis, groups]) => {
        setAccounts(accs)
        setInstitutions(fis)
        setByCustodian(groups)
      })
      .catch(err => setLoadError(err instanceof Error ? err.message : 'Erro ao carregar.'))
      .finally(() => setLoading(false))
  }, [me])

  useEffect(() => { localStorage.setItem('accounts-tab', tab) }, [tab])

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

  return (
    <AppLayout user={me}>
      <div className="w-full">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <h1 className="text-xl font-semibold text-gray-900 dark:text-white">Contas</h1>
            <div className="ml-4 inline-flex rounded-lg border border-gray-200 dark:border-gray-700 overflow-hidden">
              {([
                { id: 'contas' as Tab, label: 'Contas' },
                { id: 'ativos' as Tab, label: 'Ativos' },
              ]).map(t => (
                <button
                  key={t.id}
                  onClick={() => setTab(t.id)}
                  className={`px-4 py-1.5 text-sm transition-colors ${
                    tab === t.id
                      ? 'bg-indigo-50 dark:bg-indigo-900/40 text-indigo-700 dark:text-indigo-300 font-medium'
                      : 'text-gray-500 hover:text-gray-900 dark:hover:text-white hover:bg-gray-50 dark:hover:bg-gray-800'
                  }`}
                >
                  {t.label}
                </button>
              ))}
            </div>
          </div>
          {tab === 'contas' && (
            <button
              onClick={() => { setEditing(undefined); setModalOpen(true) }}
              className="px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-700 text-white text-sm font-medium transition-colors"
            >
              + Nova Conta
            </button>
          )}
        </div>

        {tab === 'ativos' ? (
          <ByCustodianView groups={byCustodian} loading={loading} loadError={loadError} />
        ) : (
        <div className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-800 overflow-hidden">
          {loading ? (
            <div className="p-12 text-center text-sm text-gray-400 dark:text-gray-600">Carregando…</div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-200 dark:border-gray-800">
                  {['Nome', 'Tipo', 'Instituição', 'Moeda', ''].map((h, i) => (
                    <th key={i} className="text-left px-4 py-3 text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
                {accounts.map(acc => (
                  <tr key={acc.id} className="hover:bg-gray-50 dark:hover:bg-gray-800/50 transition-colors">
                    <td className="px-4 py-3">
                      <p className="font-medium text-gray-900 dark:text-white">{acc.name}</p>
                      {acc.account_info && (
                        <p className="text-xs text-gray-400 dark:text-gray-600 mt-0.5">{acc.account_info}</p>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <span className={`inline-flex px-2 py-0.5 rounded-full text-xs font-medium ${accountTypeBadge(acc.account_type)}`}>
                        {accountTypeLabel(acc.account_type)}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-gray-500 dark:text-gray-400">
                      {acc.financial_institution_name}
                    </td>
                    <td className="px-4 py-3">
                      <span className={`inline-flex px-2 py-0.5 rounded-full text-xs font-medium ${currencyBadge(acc.currency)}`}>
                        {acc.currency}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2 justify-end">
                        <button
                          onClick={() => { setEditing(acc); setModalOpen(true) }}
                          className="px-3 py-1 text-xs rounded-lg border border-gray-200 dark:border-gray-700 text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
                        >
                          Editar
                        </button>
                        <button
                          onClick={() => setConfirmDeactivate(acc)}
                          className="px-3 py-1 text-xs rounded-lg border border-red-200 dark:border-red-900 text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors"
                        >
                          Desativar
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
                {accounts.length === 0 && (
                  <tr>
                    <td colSpan={5} className="px-4 py-12 text-center text-sm text-gray-400 dark:text-gray-600">
                      Nenhuma conta cadastrada.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          )}
        </div>
        )}
      </div>

      {modalOpen && institutions.length > 0 && (
        <Modal
          initial={editing}
          institutions={institutions}
          onSave={handleSave}
          onClose={() => setModalOpen(false)}
        />
      )}

      {confirmDeactivate && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="w-full max-w-sm bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-700 shadow-xl p-6">
            <h2 className="text-base font-semibold text-gray-900 dark:text-white mb-2">Desativar conta?</h2>
            <p className="text-sm text-gray-500 dark:text-gray-400 mb-6">
              <strong>{confirmDeactivate.name}</strong> será desativada e não aparecerá mais nas listas.
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
