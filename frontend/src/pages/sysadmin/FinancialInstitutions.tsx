import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Plus } from 'lucide-react'
import { api, type FinancialInstitutionOut, type UserOut } from '../../lib/api'
import AppLayout from '../../components/AppLayout'
import { Card, PageHeader } from '../../components/ui'

const LOGO_COLORS: Record<string, string> = {
  itau:        'bg-orange-500',
  xp:          'bg-black dark:bg-gray-700',
  avenue:      'bg-blue-600',
  btg:         'bg-yellow-500',
  bradesco:    'bg-red-600',
  santander:   'bg-red-700',
  mercadopago: 'bg-sky-500',
  wise:        'bg-green-500',
  coinbase:    'bg-blue-500',
  clear:       'bg-violet-600',
  caixa:       'bg-blue-800',
}

// Maps logo_slug to domain for favicon lookup
const LOGO_DOMAINS: Record<string, string> = {
  itau:        'itau.com.br',
  xp:          'xpi.com.br',
  avenue:      'avenue.us',
  btg:         'btgpactual.com',
  bradesco:    'bradesco.com.br',
  santander:   'santander.com.br',
  mercadopago: 'mercadopago.com.br',
  wise:        'wise.com',
  coinbase:    'coinbase.com',
  clear:       'clear.com.br',
  caixa:       'caixa.gov.br',
}

function getLogoUrl(slug: string): string | null {
  const domain = LOGO_DOMAINS[slug]
  if (!domain) return null
  return `https://www.google.com/s2/favicons?sz=64&domain=${domain}`
}

function InstitutionLogo({ fi }: { fi: FinancialInstitutionOut }) {
  const [imgFailed, setImgFailed] = useState(false)
  const logoUrl = fi.logo_slug ? getLogoUrl(fi.logo_slug) : null

  if (logoUrl && !imgFailed) {
    return (
      <div className="w-9 h-9 rounded-lg bg-white dark:bg-gray-800 flex items-center justify-center overflow-hidden shrink-0 border border-gray-100 dark:border-gray-700">
        <img
          src={logoUrl}
          alt={fi.short_name}
          className="w-7 h-7 object-contain"
          onError={() => setImgFailed(true)}
        />
      </div>
    )
  }

  const color = fi.logo_slug ? (LOGO_COLORS[fi.logo_slug] ?? 'bg-gray-400') : 'bg-gray-400'
  const initials = fi.short_name.slice(0, 2).toUpperCase()
  return (
    <div className={`w-9 h-9 rounded-lg ${color} flex items-center justify-center text-white text-xs font-bold shrink-0`}>
      {initials}
    </div>
  )
}

interface ModalProps {
  initial?: FinancialInstitutionOut
  onSave: (data: { long_name: string; short_name: string; logo_slug: string | null }) => Promise<void>
  onClose: () => void
}

function Modal({ initial, onSave, onClose }: ModalProps) {
  const [longName, setLongName] = useState(initial?.long_name ?? '')
  const [shortName, setShortName] = useState(initial?.short_name ?? '')
  const [logoSlug, setLogoSlug] = useState(initial?.logo_slug ?? '')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    setSaving(true)
    try {
      await onSave({ long_name: longName, short_name: shortName, logo_slug: logoSlug.trim() || null })
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
          {initial ? 'Editar Instituição' : 'Nova Instituição Financeira'}
        </h2>
        <form onSubmit={handleSubmit} className="space-y-4">
          {[
            { label: 'Nome completo', value: longName, set: setLongName, placeholder: 'Caixa Econômica Federal' },
            { label: 'Nome curto', value: shortName, set: setShortName, placeholder: 'Caixa' },
            { label: 'Logo slug', value: logoSlug, set: setLogoSlug, placeholder: 'caixa (opcional)' },
          ].map(({ label, value, set, placeholder }) => (
            <div key={label}>
              <label className="block text-sm text-gray-700 dark:text-gray-300 mb-1">{label}</label>
              <input
                type="text"
                value={value}
                onChange={e => set(e.target.value)}
                placeholder={placeholder}
                required={label !== 'Logo slug'}
                className="w-full px-3.5 py-2 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
              />
            </div>
          ))}
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

export default function SysAdminFinancialInstitutions() {
  const navigate = useNavigate()
  const [me, setMe] = useState<UserOut | null>(null)
  const [items, setItems] = useState<FinancialInstitutionOut[]>([])
  const [loading, setLoading] = useState(true)
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<FinancialInstitutionOut | undefined>(undefined)
  const [confirmDeactivate, setConfirmDeactivate] = useState<FinancialInstitutionOut | null>(null)

  useEffect(() => {
    api.me()
      .then(u => {
        if (u.role !== 'sysadmin') navigate('/dashboard')
        setMe(u)
      })
      .catch(() => navigate('/login'))
  }, [navigate])

  useEffect(() => {
    if (!me) return
    setLoading(true)
    api.listFinancialInstitutions()
      .then(setItems)
      .finally(() => setLoading(false))
  }, [me])

  async function handleSave(data: { long_name: string; short_name: string; logo_slug: string | null }) {
    if (editing) {
      const updated = await api.updateFinancialInstitution(editing.id, data)
      setItems(prev => prev.map(fi => fi.id === updated.id ? updated : fi))
    } else {
      const created = await api.createFinancialInstitution(data)
      setItems(prev => [...prev, created].sort((a, b) => a.short_name.localeCompare(b.short_name)))
    }
  }

  async function handleDeactivate(fi: FinancialInstitutionOut) {
    await api.deactivateFinancialInstitution(fi.id)
    setItems(prev => prev.filter(x => x.id !== fi.id))
    setConfirmDeactivate(null)
  }

  if (!me) return null

  return (
    <AppLayout user={me}>
      <div className="space-y-6">
        <PageHeader
          title="Instituições Financeiras"
          count={items.length}
          countLabel={`instituição${items.length === 1 ? '' : 'es'}`}
          action={
            <button
              onClick={() => { setEditing(undefined); setModalOpen(true) }}
              className="h-8 px-3 inline-flex items-center gap-1.5 rounded-lg text-[12px] bg-indigo-500 hover:bg-indigo-400 text-white transition-colors"
            >
              <Plus className="w-3.5 h-3.5" /> Nova Instituição
            </button>
          }
        />

        <Card padding="p-0"><div className="overflow-hidden rounded-2xl">
          {loading ? (
            <div className="p-12 text-center text-sm text-gray-400 dark:text-gray-600">Carregando…</div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-200 dark:border-gray-800">
                  {['', 'Nome Completo', 'Nome Curto', 'Slug', ''].map((h, i) => (
                    <th key={i} className="text-left px-4 py-3 text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
                {items.map(fi => (
                  <tr key={fi.id} className="hover:bg-gray-50 dark:hover:bg-gray-800/50 transition-colors">
                    <td className="px-4 py-3 w-12">
                      <InstitutionLogo fi={fi} />
                    </td>
                    <td className="px-4 py-3 text-gray-900 dark:text-white font-medium">{fi.long_name}</td>
                    <td className="px-4 py-3 text-gray-500 dark:text-gray-400">{fi.short_name}</td>
                    <td className="px-4 py-3 text-gray-400 dark:text-gray-600 text-xs font-mono">{fi.logo_slug ?? '—'}</td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2 justify-end">
                        <button
                          onClick={() => { setEditing(fi); setModalOpen(true) }}
                          className="px-3 py-1 text-xs rounded-lg border border-gray-200 dark:border-gray-700 text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
                        >
                          Editar
                        </button>
                        <button
                          onClick={() => setConfirmDeactivate(fi)}
                          className="px-3 py-1 text-xs rounded-lg border border-red-200 dark:border-red-900 text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors"
                        >
                          Desativar
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
                {items.length === 0 && (
                  <tr>
                    <td colSpan={5} className="px-4 py-12 text-center text-sm text-gray-400 dark:text-gray-600">
                      Nenhuma instituição cadastrada.
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
          onSave={handleSave}
          onClose={() => setModalOpen(false)}
        />
      )}

      {confirmDeactivate && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="w-full max-w-sm bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-700 shadow-xl p-6">
            <h2 className="text-base font-semibold text-gray-900 dark:text-white mb-2">Desativar instituição?</h2>
            <p className="text-sm text-gray-500 dark:text-gray-400 mb-6">
              <strong>{confirmDeactivate.short_name}</strong> será desativada e não aparecerá mais nas listas.
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
