import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  api,
  type AssetOut,
  type LancamentoOut,
  type LancamentoRequest,
  type LancamentoType,
  type UserOut,
  LANCAMENTO_TYPE_LABELS,
} from '../lib/api'
import AppLayout from '../components/AppLayout'
import LancamentoModal from '../components/LancamentoModal'

const ALL_TYPES: LancamentoType[] = [
  'COMPRA',
  'VENDA',
  'DIVIDENDO',
  'JUROS',
  'JCP',
  'COME_COTAS',
  'BONIFICACAO',
  'SUBSCRICAO',
]

function typeBadge(t: LancamentoType): string {
  const map: Record<LancamentoType, string> = {
    COMPRA: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400',
    VENDA: 'bg-rose-100 text-rose-700 dark:bg-rose-900/30 dark:text-rose-400',
    DIVIDENDO: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400',
    JUROS: 'bg-cyan-100 text-cyan-700 dark:bg-cyan-900/30 dark:text-cyan-400',
    JCP: 'bg-indigo-100 text-indigo-700 dark:bg-indigo-900/30 dark:text-indigo-400',
    COME_COTAS: 'bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-400',
    BONIFICACAO: 'bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400',
    SUBSCRICAO: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400',
  }
  return map[t]
}

function fmtMoney(n: number, currency: string) {
  return n.toLocaleString('pt-BR', { style: 'currency', currency })
}

function fmtNumber(n: number | null) {
  if (n == null) return '—'
  return n.toLocaleString('pt-BR', { maximumFractionDigits: 8 })
}

export default function Lancamentos() {
  const navigate = useNavigate()
  const [me, setMe] = useState<UserOut | null>(null)
  const [items, setItems] = useState<LancamentoOut[]>([])
  const [assets, setAssets] = useState<AssetOut[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<LancamentoOut | undefined>(undefined)
  const [confirmDeactivate, setConfirmDeactivate] = useState<LancamentoOut | null>(null)

  const [assetFilter, setAssetFilter] = useState('')
  const [typeFilter, setTypeFilter] = useState<LancamentoType | ''>('')
  const [fromDate, setFromDate] = useState('')
  const [toDate, setToDate] = useState('')
  const [includeInactive, setIncludeInactive] = useState(false)

  useEffect(() => {
    api.me()
      .then(u => setMe(u))
      .catch(() => navigate('/login'))
  }, [navigate])

  useEffect(() => {
    if (!me) return
    setLoading(true)
    setLoadError('')
    Promise.all([
      api.listLancamentos({
        asset_id: assetFilter || undefined,
        type: typeFilter || undefined,
        from: fromDate || undefined,
        to: toDate || undefined,
        include_inactive: includeInactive,
        page_size: 200,
      }),
      api.listAssets({ include_inactive: true }),
    ])
      .then(([page, as]) => {
        setItems(page.items)
        setAssets(as)
      })
      .catch(err => setLoadError(err instanceof Error ? err.message : 'Erro ao carregar.'))
      .finally(() => setLoading(false))
  }, [me, assetFilter, typeFilter, fromDate, toDate, includeInactive])

  async function handleSave(data: LancamentoRequest) {
    if (editing) {
      const updated = await api.updateLancamento(editing.id, data)
      setItems(prev => prev.map(l => l.id === updated.id ? updated : l))
    } else {
      const created = await api.createLancamento(data)
      setItems(prev => [created, ...prev])
    }
  }

  async function handleDeactivate(l: LancamentoOut) {
    await api.deactivateLancamento(l.id)
    if (includeInactive) {
      setItems(prev => prev.map(x => x.id === l.id ? { ...x, is_active: false } : x))
    } else {
      setItems(prev => prev.filter(x => x.id !== l.id))
    }
    setConfirmDeactivate(null)
  }

  if (!me) return null

  return (
    <AppLayout user={me}>
      <div className="w-full">
        <div className="flex items-center justify-between mb-6">
          <h1 className="text-xl font-semibold text-gray-900 dark:text-white">Lançamentos</h1>
          <button
            onClick={() => { setEditing(undefined); setModalOpen(true) }}
            disabled={assets.length === 0}
            className="px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white text-sm font-medium transition-colors"
            title={assets.length === 0 ? 'Cadastre um ativo antes' : undefined}
          >
            + Novo Lançamento
          </button>
        </div>

        <div className="flex flex-wrap gap-3 mb-4 items-end">
          <div className="min-w-[220px]">
            <label className="block text-xs text-gray-500 dark:text-gray-400 mb-1">Ativo</label>
            <select
              value={assetFilter}
              onChange={e => setAssetFilter(e.target.value)}
              className="w-full px-3 py-1.5 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
            >
              <option value="">Todos</option>
              {assets.map(a => (
                <option key={a.id} value={a.id}>
                  {a.ticker ? `${a.ticker} — ` : ''}{a.name}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-xs text-gray-500 dark:text-gray-400 mb-1">Tipo</label>
            <select
              value={typeFilter}
              onChange={e => setTypeFilter(e.target.value as LancamentoType | '')}
              className="px-3 py-1.5 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
            >
              <option value="">Todos</option>
              {ALL_TYPES.map(t => <option key={t} value={t}>{LANCAMENTO_TYPE_LABELS[t]}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-xs text-gray-500 dark:text-gray-400 mb-1">De</label>
            <input
              type="date"
              value={fromDate}
              onChange={e => setFromDate(e.target.value)}
              className="px-3 py-1.5 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
          </div>
          <div>
            <label className="block text-xs text-gray-500 dark:text-gray-400 mb-1">Até</label>
            <input
              type="date"
              value={toDate}
              onChange={e => setToDate(e.target.value)}
              className="px-3 py-1.5 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
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
                  {['Data', 'Tipo', 'Ativo', 'Quantidade', 'Preço', 'Líquido', 'Moeda', ''].map((h, i) => (
                    <th key={i} className="text-left px-4 py-3 text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
                {items.map(l => (
                  <tr key={l.id} className={`hover:bg-gray-50 dark:hover:bg-gray-800/50 transition-colors ${l.is_active ? '' : 'opacity-60'}`}>
                    <td className="px-4 py-3 text-gray-700 dark:text-gray-300 text-xs">{l.event_date}</td>
                    <td className="px-4 py-3">
                      <span className={`inline-flex px-2 py-0.5 rounded-full text-xs font-medium ${typeBadge(l.type)}`}>
                        {l.type_label}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-gray-900 dark:text-white">
                      {l.asset_ticker && <span className="font-mono text-xs text-gray-500 dark:text-gray-400 mr-2">{l.asset_ticker}</span>}
                      <span className="font-medium">{l.asset_name}</span>
                    </td>
                    <td className="px-4 py-3 text-right text-gray-700 dark:text-gray-300 font-mono text-xs">{fmtNumber(l.quantity)}</td>
                    <td className="px-4 py-3 text-right text-gray-700 dark:text-gray-300 font-mono text-xs">{fmtNumber(l.unit_price)}</td>
                    <td className="px-4 py-3 text-right text-gray-900 dark:text-white font-medium">{fmtMoney(l.net_amount, l.currency)}</td>
                    <td className="px-4 py-3 text-xs text-gray-500 dark:text-gray-400">{l.currency}</td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2 justify-end">
                        <button
                          onClick={() => { setEditing(l); setModalOpen(true) }}
                          className="px-3 py-1 text-xs rounded-lg border border-gray-200 dark:border-gray-700 text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
                        >
                          Editar
                        </button>
                        {l.is_active && (
                          <button
                            onClick={() => setConfirmDeactivate(l)}
                            className="px-3 py-1 text-xs rounded-lg border border-red-200 dark:border-red-900 text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors"
                          >
                            Desativar
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
                {items.length === 0 && (
                  <tr>
                    <td colSpan={8} className="px-4 py-12 text-center text-sm text-gray-400 dark:text-gray-600">
                      Nenhum lançamento encontrado.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {modalOpen && (
        <LancamentoModal
          initial={editing}
          assets={assets}
          onSave={handleSave}
          onClose={() => { setModalOpen(false); setEditing(undefined) }}
        />
      )}

      {confirmDeactivate && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="w-full max-w-sm bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-700 shadow-xl p-6">
            <h2 className="text-base font-semibold text-gray-900 dark:text-white mb-2">Desativar lançamento?</h2>
            <p className="text-sm text-gray-500 dark:text-gray-400 mb-6">
              <strong>{confirmDeactivate.type_label}</strong> de <strong>{confirmDeactivate.asset_name}</strong> será desativado.
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
