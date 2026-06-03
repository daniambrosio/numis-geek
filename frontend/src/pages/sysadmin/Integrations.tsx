import { useEffect, useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { Plus, Plug, CheckCircle2, XCircle, AlertCircle, ExternalLink } from 'lucide-react'
import {
  api,
  type IntegrationCredentialOut,
  type IntegrationProvider,
  type ProviderCatalogEntry,
  type UserOut,
} from '../../lib/api'
import AppLayout from '../../components/AppLayout'
import { Card, PageHeader } from '../../components/ui'
import { useEscapeKey } from '../../lib/useEscapeKey'

const PROVIDER_COLOR: Record<IntegrationProvider, string> = {
  BCB: 'bg-emerald-500',
  BRAPI: 'bg-yellow-500',
  FINNHUB: 'bg-indigo-500',
  YFINANCE: 'bg-purple-500',
  NOTION: 'bg-gray-700',
}

interface ModalProps {
  initial?: IntegrationCredentialOut
  providers: ProviderCatalogEntry[]
  onSave: () => Promise<void>
  onClose: () => void
}

function Modal({ initial, providers, onSave, onClose }: ModalProps) {
  const [provider, setProvider] = useState<IntegrationProvider>(initial?.provider ?? 'BRAPI')
  const [keyName, setKeyName] = useState(initial?.key_name ?? 'API_TOKEN')
  const [label, setLabel] = useState(initial?.label ?? '')
  const [secret, setSecret] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    setSaving(true)
    try {
      if (initial) {
        await api.updateIntegration(initial.id, {
          label: label.trim() || null,
          secret_value: secret.trim() || null,
        })
      } else {
        await api.createIntegration({
          provider,
          key_name: keyName.trim(),
          label: label.trim() || null,
          secret_value: secret.trim(),
        })
      }
      await onSave()
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Erro ao salvar.')
    } finally {
      setSaving(false)
    }
  }

  const editable = providers.filter(p => p.requires_credentials)

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="w-full max-w-md bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-700 shadow-xl p-6">
        <h2 className="text-base font-semibold text-gray-900 dark:text-white mb-5">
          {initial ? 'Editar credencial' : 'Nova credencial'}
        </h2>
        <form onSubmit={handleSubmit} className="space-y-4">
          {!initial && (
            <>
              <div>
                <label className="block text-sm text-gray-700 dark:text-gray-300 mb-1">Provider</label>
                <select
                  value={provider}
                  onChange={e => setProvider(e.target.value as IntegrationProvider)}
                  className="w-full px-3.5 py-2 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                >
                  {editable.map(p => (
                    <option key={p.provider} value={p.provider}>{p.label}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-sm text-gray-700 dark:text-gray-300 mb-1">Key name</label>
                <input
                  type="text"
                  value={keyName}
                  onChange={e => setKeyName(e.target.value)}
                  placeholder="API_TOKEN"
                  required
                  className="w-full px-3.5 py-2 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                />
              </div>
            </>
          )}
          <div>
            <label className="block text-sm text-gray-700 dark:text-gray-300 mb-1">Label (opcional)</label>
            <input
              type="text"
              value={label}
              onChange={e => setLabel(e.target.value)}
              placeholder="Ex: Token principal"
              className="w-full px-3.5 py-2 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
          </div>
          <div>
            <label className="block text-sm text-gray-700 dark:text-gray-300 mb-1">
              Secret value {initial && <span className="text-xs text-gray-400">(deixe vazio pra manter)</span>}
            </label>
            <input
              type="password"
              value={secret}
              onChange={e => setSecret(e.target.value)}
              placeholder="••••"
              required={!initial}
              className="w-full px-3.5 py-2 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 font-mono"
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

function TestResultBadge({ row }: { row: IntegrationCredentialOut }) {
  if (row.last_test_result === 'SUCCESS') {
    return <span className="inline-flex items-center gap-1 text-xs text-emerald-600 dark:text-emerald-400"><CheckCircle2 className="w-3.5 h-3.5" /> OK</span>
  }
  if (row.last_test_result === 'FAILED') {
    return <span className="inline-flex items-center gap-1 text-xs text-red-600 dark:text-red-400" title={row.last_test_message ?? ''}><XCircle className="w-3.5 h-3.5" /> Falhou</span>
  }
  return <span className="inline-flex items-center gap-1 text-xs text-gray-400 dark:text-gray-600"><AlertCircle className="w-3.5 h-3.5" /> Não testado</span>
}

export default function SysAdminIntegrations() {
  const navigate = useNavigate()
  const [me, setMe] = useState<UserOut | null>(null)
  const [providers, setProviders] = useState<ProviderCatalogEntry[]>([])
  const [creds, setCreds] = useState<IntegrationCredentialOut[]>([])
  const [loading, setLoading] = useState(true)
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<IntegrationCredentialOut | undefined>()
  const [testing, setTesting] = useState<string | null>(null)
  const [confirmDelete, setConfirmDelete] = useState<IntegrationCredentialOut | null>(null)
  useEscapeKey(() => { if (confirmDelete) setConfirmDelete(null); else if (modalOpen) { setModalOpen(false); setEditing(undefined) } })

  useEffect(() => {
    api.me()
      .then(u => {
        if (u.role !== 'sysadmin') navigate('/dashboard')
        setMe(u)
      })
      .catch(() => navigate('/login'))
  }, [navigate])

  async function refresh() {
    const [provs, cs] = await Promise.all([
      api.listIntegrationProviders(),
      api.listIntegrations(),
    ])
    setProviders(provs)
    setCreds(cs)
  }

  useEffect(() => {
    if (!me) return
    setLoading(true)
    refresh().finally(() => setLoading(false))
  }, [me])

  async function handleTest(c: IntegrationCredentialOut) {
    setTesting(c.id)
    try {
      await api.testIntegration(c.id)
      await refresh()
    } finally {
      setTesting(null)
    }
  }

  async function handleDelete(c: IntegrationCredentialOut) {
    await api.deleteIntegration(c.id)
    setConfirmDelete(null)
    await refresh()
  }

  if (!me) return null

  return (
    <AppLayout user={me}>
      <div className="space-y-6">
        <PageHeader
          title="Integrações"
          count={creds.length}
          countLabel="credencial(is)"
          action={
            <button
              onClick={() => { setEditing(undefined); setModalOpen(true) }}
              className="h-8 px-3 inline-flex items-center gap-1.5 rounded-lg text-[12px] bg-indigo-500 hover:bg-indigo-400 text-white transition-colors"
            >
              <Plus className="w-3.5 h-3.5" /> Nova credencial
            </button>
          }
        />

        {/* Provider catalog */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          {providers.map(p => {
            const ownCreds = creds.filter(c => c.provider === p.provider)
            return (
              <Card key={p.provider}>
                <div className="flex items-start gap-3">
                  <div className={`w-10 h-10 rounded-lg ${PROVIDER_COLOR[p.provider]} flex items-center justify-center shrink-0`}>
                    <Plug className="w-5 h-5 text-white" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="font-medium text-sm text-gray-900 dark:text-white">{p.label}</div>
                    <div className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
                      {p.requires_credentials
                        ? `${ownCreds.length} credencial(is)`
                        : 'Sem credenciais necessárias'}
                    </div>
                    {p.provider === 'BCB' && (
                      <Link to="/sysadmin/ptax" className="inline-flex items-center gap-1 mt-2 text-xs text-indigo-600 dark:text-indigo-400 hover:underline">
                        Sincronizar PTAX <ExternalLink className="w-3 h-3" />
                      </Link>
                    )}
                  </div>
                </div>
              </Card>
            )
          })}
        </div>

        <Card padding="p-0"><div className="overflow-hidden rounded-2xl">
          {loading ? (
            <div className="p-12 text-center text-sm text-gray-400 dark:text-gray-600">Carregando…</div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-200 dark:border-gray-800">
                  {['Provider', 'Key', 'Label', 'Valor', 'Teste', ''].map((h, i) => (
                    <th key={i} className="text-left px-4 py-3 text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
                {creds.map(c => (
                  <tr key={c.id} className="hover:bg-gray-50 dark:hover:bg-gray-800/50 transition-colors">
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <div className={`w-6 h-6 rounded-md ${PROVIDER_COLOR[c.provider]} flex items-center justify-center shrink-0`}>
                          <Plug className="w-3 h-3 text-white" />
                        </div>
                        <span className="text-gray-900 dark:text-white font-medium">{c.provider}</span>
                      </div>
                    </td>
                    <td className="px-4 py-3 text-gray-500 dark:text-gray-400 font-mono text-xs">{c.key_name}</td>
                    <td className="px-4 py-3 text-gray-600 dark:text-gray-300">{c.label ?? '—'}</td>
                    <td className="px-4 py-3 text-gray-400 dark:text-gray-600 font-mono text-xs">{c.secret_preview}</td>
                    <td className="px-4 py-3"><TestResultBadge row={c} /></td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2 justify-end">
                        <button
                          onClick={() => handleTest(c)}
                          disabled={testing === c.id}
                          className="px-3 py-1 text-xs rounded-lg border border-gray-200 dark:border-gray-700 text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-800 disabled:opacity-50 transition-colors"
                        >
                          {testing === c.id ? 'Testando…' : 'Testar'}
                        </button>
                        <button
                          onClick={() => { setEditing(c); setModalOpen(true) }}
                          className="px-3 py-1 text-xs rounded-lg border border-gray-200 dark:border-gray-700 text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
                        >
                          Editar
                        </button>
                        <button
                          onClick={() => setConfirmDelete(c)}
                          className="px-3 py-1 text-xs rounded-lg border border-red-200 dark:border-red-900 text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors"
                        >
                          Excluir
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
                {creds.length === 0 && (
                  <tr>
                    <td colSpan={6} className="px-4 py-12 text-center text-sm text-gray-400 dark:text-gray-600">
                      Nenhuma credencial cadastrada. Clique em "Nova credencial" pra adicionar.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          )}
        </div></Card>
      </div>

      {modalOpen && (
        <Modal
          initial={editing}
          providers={providers}
          onSave={refresh}
          onClose={() => setModalOpen(false)}
        />
      )}

      {confirmDelete && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="w-full max-w-sm bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-700 shadow-xl p-6">
            <h2 className="text-base font-semibold text-gray-900 dark:text-white mb-2">Excluir credencial?</h2>
            <p className="text-sm text-gray-500 dark:text-gray-400 mb-6">
              <strong>{confirmDelete.provider}/{confirmDelete.key_name}</strong> será removida permanentemente.
            </p>
            <div className="flex justify-end gap-3">
              <button onClick={() => setConfirmDelete(null)} className="px-4 py-2 rounded-lg text-sm text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors">
                Cancelar
              </button>
              <button onClick={() => handleDelete(confirmDelete)} className="px-4 py-2 rounded-lg bg-red-600 hover:bg-red-700 text-white text-sm font-medium transition-colors">
                Excluir
              </button>
            </div>
          </div>
        </div>
      )}
    </AppLayout>
  )
}
