import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Plus, Upload, Trash2 } from 'lucide-react'
import { api, type FinancialInstitutionOut, type UserOut } from '../../lib/api'
import AppLayout from '../../components/AppLayout'
import { Card, FILogo, PageHeader } from '../../components/ui'
import { refreshFiLogos, useFiLogosById } from '../../lib/fiLogos'
import { useEscapeKey } from '../../lib/useEscapeKey'

// Espelha o whitelist do backend (services/fi_logo_storage.py) — validar aqui
// evita round-trip só pra receber 415/413.
const ACCEPTED_MIME = ['image/png', 'image/jpeg', 'image/webp', 'image/svg+xml']
const MAX_LOGO_BYTES = 512 * 1024

export interface FiFormData {
  long_name: string
  short_name: string
  logo_slug: string | null
  brand_color: string | null
}

interface ModalProps {
  initial?: FinancialInstitutionOut
  onSave: (data: FiFormData, logoFile: File | null, removeLogo: boolean) => Promise<void>
  onClose: () => void
}

function Modal({ initial, onSave, onClose }: ModalProps) {
  const [longName, setLongName] = useState(initial?.long_name ?? '')
  const [shortName, setShortName] = useState(initial?.short_name ?? '')
  const [logoSlug, setLogoSlug] = useState(initial?.logo_slug ?? '')
  const [brandColor, setBrandColor] = useState(initial?.brand_color ?? '')
  const [logoFile, setLogoFile] = useState<File | null>(null)
  const [logoPreview, setLogoPreview] = useState<string | null>(null)
  const [removeLogo, setRemoveLogo] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const fileInput = useRef<HTMLInputElement>(null)
  const byId = useFiLogosById()

  const storedLogo = initial ? byId[initial.id]?.data_url ?? null : null
  const shownLogo = logoPreview ?? (removeLogo ? null : storedLogo)

  // Object URL do arquivo escolhido — revogado ao trocar/desmontar.
  useEffect(() => {
    if (!logoFile) { setLogoPreview(null); return }
    const url = URL.createObjectURL(logoFile)
    setLogoPreview(url)
    return () => URL.revokeObjectURL(url)
  }, [logoFile])

  function handlePick(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    e.target.value = ''  // permite reescolher o mesmo arquivo
    if (!file) return
    if (!ACCEPTED_MIME.includes(file.type)) {
      setError('Formato não suportado. Use PNG, JPG, WEBP ou SVG.')
      return
    }
    if (file.size > MAX_LOGO_BYTES) {
      setError(`Logo de ${(file.size / 1024).toFixed(0)} KB excede o limite de ${MAX_LOGO_BYTES / 1024} KB.`)
      return
    }
    setError('')
    setRemoveLogo(false)
    setLogoFile(file)
  }

  function handleRemoveLogo() {
    setLogoFile(null)
    setRemoveLogo(true)
    setError('')
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    setSaving(true)
    try {
      await onSave(
        {
          long_name: longName,
          short_name: shortName,
          logo_slug: logoSlug.trim() || null,
          brand_color: brandColor.trim() || null,
        },
        logoFile,
        removeLogo,
      )
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

          <div>
            <label className="block text-sm text-gray-700 dark:text-gray-300 mb-1">Logo</label>
            <div className="flex items-center gap-3">
              <div className="w-12 h-12 rounded-lg flex items-center justify-center overflow-hidden shrink-0 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700">
                {shownLogo ? (
                  <img src={shownLogo} alt="Prévia do logo" className="w-full h-full object-contain p-1" />
                ) : (
                  <span
                    className="w-full h-full flex items-center justify-center text-white text-xs font-semibold"
                    style={{ background: brandColor.trim() || '#94a3b8' }}
                  >
                    {(shortName || '··').slice(0, 2).toUpperCase()}
                  </span>
                )}
              </div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => fileInput.current?.click()}
                  className="px-3 py-1.5 inline-flex items-center gap-1.5 text-xs rounded-lg border border-gray-300 dark:border-gray-700 text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
                >
                  <Upload className="w-3.5 h-3.5" /> {shownLogo ? 'Trocar' : 'Enviar'}
                </button>
                {shownLogo && (
                  <button
                    type="button"
                    onClick={handleRemoveLogo}
                    className="px-3 py-1.5 inline-flex items-center gap-1.5 text-xs rounded-lg border border-red-200 dark:border-red-900 text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors"
                  >
                    <Trash2 className="w-3.5 h-3.5" /> Remover
                  </button>
                )}
                <input
                  ref={fileInput}
                  type="file"
                  accept={ACCEPTED_MIME.join(',')}
                  onChange={handlePick}
                  aria-label="Arquivo do logo"
                  className="hidden"
                />
              </div>
            </div>
            <p className="mt-1.5 text-xs text-gray-400 dark:text-gray-600">
              PNG, JPG, WEBP ou SVG · até {MAX_LOGO_BYTES / 1024} KB. Sem logo, a instituição aparece com as iniciais sobre a cor da marca.
            </p>
          </div>

          <div>
            <label className="block text-sm text-gray-700 dark:text-gray-300 mb-1">Cor da marca</label>
            <div className="flex items-center gap-2">
              <input
                type="color"
                value={/^#[0-9a-fA-F]{6}$/.test(brandColor.trim()) ? brandColor.trim() : '#94a3b8'}
                onChange={e => setBrandColor(e.target.value)}
                className="w-10 h-9 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 cursor-pointer"
                aria-label="Cor da marca"
              />
              <input
                type="text"
                value={brandColor}
                onChange={e => setBrandColor(e.target.value)}
                placeholder="#820AD1 (opcional)"
                className="flex-1 px-3.5 py-2 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm font-mono focus:outline-none focus:ring-2 focus:ring-indigo-500"
              />
              {brandColor.trim() && (
                <button
                  type="button"
                  onClick={() => setBrandColor('')}
                  className="px-3 py-2 text-xs rounded-lg text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
                >
                  Limpar
                </button>
              )}
            </div>
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

export default function SysAdminFinancialInstitutions() {
  const navigate = useNavigate()
  const [me, setMe] = useState<UserOut | null>(null)
  const [items, setItems] = useState<FinancialInstitutionOut[]>([])
  const [loading, setLoading] = useState(true)
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<FinancialInstitutionOut | undefined>(undefined)
  const [confirmDeactivate, setConfirmDeactivate] = useState<FinancialInstitutionOut | null>(null)
  useEscapeKey(() => { if (confirmDeactivate) setConfirmDeactivate(null); else if (modalOpen) { setModalOpen(false); setEditing(undefined) } })

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

  async function handleSave(data: FiFormData, logoFile: File | null, removeLogo: boolean) {
    const isNew = !editing
    // O upload é um segundo request (multipart) — numa instituição nova ele só
    // pode rodar depois do POST, que é quem cria o id.
    let saved = editing
      ? await api.updateFinancialInstitution(editing.id, data)
      : await api.createFinancialInstitution(data)
    if (logoFile) {
      saved = await api.uploadFinancialInstitutionLogo(saved.id, logoFile)
    } else if (removeLogo && saved.has_logo) {
      saved = await api.deleteFinancialInstitutionLogo(saved.id)
    }
    setItems(prev => isNew
      ? [...prev, saved].sort((a, b) => a.short_name.localeCompare(b.short_name))
      : prev.map(fi => fi.id === saved.id ? saved : fi))
    // Logo/cor são consumidos pelo <FILogo> do app inteiro via cache global.
    refreshFiLogos()
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
                      <FILogo slug={fi.logo_slug} shortName={fi.short_name} fiId={fi.id} size="lg" />
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
