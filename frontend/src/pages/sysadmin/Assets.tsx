import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, type AssetClass, type AssetOut, type AssetRequest, type FinancialInstitutionOut, type UserOut, type WorkspaceOut } from '../../lib/api'
import AppLayout from '../../components/AppLayout'
import AssetModal, { CLASS_LABELS } from '../../components/AssetModal'

const ALL_CLASSES = Object.keys(CLASS_LABELS) as AssetClass[]

function classBadge(c: AssetClass): string {
  const map: Record<AssetClass, string> = {
    STOCK_BR: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400',
    STOCK_US: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400',
    FII: 'bg-cyan-100 text-cyan-700 dark:bg-cyan-900/30 dark:text-cyan-400',
    ETF: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400',
    REIT: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400',
    BOND: 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300',
    FIXED_INCOME: 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400',
    FUND: 'bg-violet-100 text-violet-700 dark:bg-violet-900/30 dark:text-violet-400',
    CRYPTO: 'bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-400',
    REAL_ESTATE: 'bg-pink-100 text-pink-700 dark:bg-pink-900/30 dark:text-pink-400',
    VEHICLE: 'bg-indigo-100 text-indigo-700 dark:bg-indigo-900/30 dark:text-indigo-400',
  }
  return map[c]
}

function currencyBadge(c: string) {
  return c === 'USD'
    ? 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400'
    : 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400'
}

export default function SysadminAssets() {
  const navigate = useNavigate()
  const [me, setMe] = useState<UserOut | null>(null)
  const [assets, setAssets] = useState<AssetOut[]>([])
  const [institutions, setInstitutions] = useState<FinancialInstitutionOut[]>([])
  const [workspaces, setWorkspaces] = useState<WorkspaceOut[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<AssetOut | undefined>(undefined)
  const [confirmDeactivate, setConfirmDeactivate] = useState<AssetOut | null>(null)

  // Filters
  const [workspaceFilter, setWorkspaceFilter] = useState('')   // '' = Todos
  const [classFilter, setClassFilter] = useState<AssetClass | ''>('')
  const [currencyFilter, setCurrencyFilter] = useState<'' | 'BRL' | 'USD'>('')
  const [search, setSearch] = useState('')
  const [includeInactive, setIncludeInactive] = useState(false)

  useEffect(() => {
    api.me()
      .then(u => {
        if (u.role !== 'sysadmin') {
          navigate('/dashboard')
          return
        }
        setMe(u)
      })
      .catch(() => navigate('/login'))
  }, [navigate])

  useEffect(() => {
    if (!me) return
    setLoading(true)
    setLoadError('')
    Promise.all([
      api.listAssets({
        workspace_id: workspaceFilter || undefined,
        asset_class: classFilter || undefined,
        include_inactive: includeInactive,
        search: search.trim() || undefined,
      }),
      api.listFinancialInstitutions(),
      api.listWorkspaces(),
    ])
      .then(([as, fis, wss]) => {
        setAssets(as)
        setInstitutions(fis)
        setWorkspaces(wss)
      })
      .catch(err => setLoadError(err instanceof Error ? err.message : 'Erro ao carregar.'))
      .finally(() => setLoading(false))
  }, [me, workspaceFilter, classFilter, includeInactive, search])

  const filtered = assets.filter(a => !currencyFilter || a.currency === currencyFilter)

  async function handleSave(data: AssetRequest) {
    if (editing) {
      const updated = await api.updateAsset(editing.id, data)
      setAssets(prev => prev.map(a => a.id === updated.id ? updated : a))
    } else {
      const created = await api.createAsset(data)
      setAssets(prev => [...prev, created].sort((a, b) => a.name.localeCompare(b.name)))
    }
  }

  async function handleDeactivate(asset: AssetOut) {
    await api.deactivateAsset(asset.id)
    if (includeInactive) {
      setAssets(prev => prev.map(a => a.id === asset.id ? { ...a, is_active: false } : a))
    } else {
      setAssets(prev => prev.filter(a => a.id !== asset.id))
    }
    setConfirmDeactivate(null)
  }

  if (!me) return null

  return (
    <AppLayout user={me}>
      <div className="w-full">
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-4">
            <h1 className="text-xl font-semibold text-gray-900 dark:text-white">Ativos (Sistema)</h1>
            <select
              value={workspaceFilter}
              onChange={e => setWorkspaceFilter(e.target.value)}
              className="px-3 py-1.5 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
            >
              <option value="">Todos os workspaces</option>
              {workspaces.map(w => (
                <option key={w.id} value={w.id}>{w.name}</option>
              ))}
            </select>
          </div>
          <button
            onClick={() => { setEditing(undefined); setModalOpen(true) }}
            disabled={!workspaceFilter && workspaces.length > 0}
            title={!workspaceFilter ? 'Selecione um workspace para criar' : undefined}
            className="px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-medium transition-colors"
          >
            + Novo Ativo
          </button>
        </div>

        <div className="flex flex-wrap gap-3 mb-4 items-end">
          <div>
            <label className="block text-xs text-gray-500 dark:text-gray-400 mb-1">Classe</label>
            <select
              value={classFilter}
              onChange={e => setClassFilter(e.target.value as AssetClass | '')}
              className="px-3 py-1.5 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
            >
              <option value="">Todas</option>
              {ALL_CLASSES.map(c => <option key={c} value={c}>{CLASS_LABELS[c]}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-xs text-gray-500 dark:text-gray-400 mb-1">Moeda</label>
            <select
              value={currencyFilter}
              onChange={e => setCurrencyFilter(e.target.value as '' | 'BRL' | 'USD')}
              className="px-3 py-1.5 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
            >
              <option value="">Todas</option>
              <option value="BRL">BRL</option>
              <option value="USD">USD</option>
            </select>
          </div>
          <div className="flex-1 min-w-[200px]">
            <label className="block text-xs text-gray-500 dark:text-gray-400 mb-1">Buscar</label>
            <input
              type="text"
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="Nome, ticker ou CNPJ"
              className="w-full px-3 py-1.5 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
          </div>
          <label className="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-300 pb-1.5">
            <input
              type="checkbox"
              checked={includeInactive}
              onChange={e => setIncludeInactive(e.target.checked)}
              className="rounded"
            />
            Mostrar inativos
          </label>
        </div>

        <div className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-800 overflow-hidden">
          {loading ? (
            <div className="p-12 text-center text-sm text-gray-400 dark:text-gray-600">Carregando…</div>
          ) : loadError ? (
            <div className="p-12 text-center text-sm text-red-500">{loadError}</div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-200 dark:border-gray-800">
                  {['Workspace', 'Ticker', 'Nome', 'Classe', 'Custodiante', 'Moeda', 'Atualizado', ''].map((h, i) => (
                    <th key={i} className="text-left px-4 py-3 text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
                {filtered.map(a => (
                  <tr key={a.id} className={`hover:bg-gray-50 dark:hover:bg-gray-800/50 transition-colors ${a.is_active ? '' : 'opacity-60'}`}>
                    <td className="px-4 py-3 text-xs text-gray-500 dark:text-gray-400">{a.workspace_name ?? a.workspace_id.slice(0, 8)}</td>
                    <td className="px-4 py-3 font-mono text-xs text-gray-700 dark:text-gray-300">{a.ticker ?? '—'}</td>
                    <td className="px-4 py-3 text-gray-900 dark:text-white font-medium">{a.name}</td>
                    <td className="px-4 py-3">
                      <span className={`inline-flex px-2 py-0.5 rounded-full text-xs font-medium ${classBadge(a.asset_class)}`}>
                        {CLASS_LABELS[a.asset_class]}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-gray-500 dark:text-gray-400">{a.financial_institution_name}</td>
                    <td className="px-4 py-3">
                      <span className={`inline-flex px-2 py-0.5 rounded-full text-xs font-medium ${currencyBadge(a.currency)}`}>
                        {a.currency}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-xs text-gray-400 dark:text-gray-600">{new Date(a.updated_at).toLocaleDateString()}</td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2 justify-end">
                        <button
                          onClick={() => { setEditing(a); setModalOpen(true) }}
                          className="px-3 py-1 text-xs rounded-lg border border-gray-200 dark:border-gray-700 text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
                        >
                          Editar
                        </button>
                        {a.is_active && (
                          <button
                            onClick={() => setConfirmDeactivate(a)}
                            className="px-3 py-1 text-xs rounded-lg border border-red-200 dark:border-red-900 text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors"
                          >
                            Desativar
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
                {filtered.length === 0 && (
                  <tr>
                    <td colSpan={8} className="px-4 py-12 text-center text-sm text-gray-400 dark:text-gray-600">
                      Nenhum ativo encontrado.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {modalOpen && institutions.length > 0 && (
        <AssetModal
          initial={editing}
          institutions={institutions}
          forcedWorkspaceId={editing?.workspace_id ?? workspaceFilter ?? undefined}
          workspaceOptions={editing ? undefined : workspaces.map(w => ({ id: w.id, name: w.name }))}
          onSave={handleSave}
          onClose={() => { setModalOpen(false); setEditing(undefined) }}
        />
      )}

      {confirmDeactivate && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="w-full max-w-sm bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-700 shadow-xl p-6">
            <h2 className="text-base font-semibold text-gray-900 dark:text-white mb-2">Desativar ativo?</h2>
            <p className="text-sm text-gray-500 dark:text-gray-400 mb-6">
              <strong>{confirmDeactivate.name}</strong> será desativado e não aparecerá mais nas listas.
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
