/* Spec 68 — Cadastros (/admin/registry): CRUD de Categorias, Fornecedores/
 * Clientes e Tags.
 *
 * Página ADMIN (member é redirecionado, como as demais /admin). As visões
 * de consumo/relatório ficam nas páginas de domínio /categories e /parties
 * (grupo Caixa & Cartões). Categorias NÃO têm seed — chegam pelo import do
 * Notion (spec 73).
 */
import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { GitMerge, Pencil, Plus, X } from 'lucide-react'
import { api, type CategoryOut, type PartyOut, type TagOut, type UserOut } from '../lib/api'
import AppLayout from '../components/AppLayout'
import { Card, PageHeader, Field, INPUT_CLS } from '../components/ui'
import { useEscapeKey } from '../lib/useEscapeKey'

// ── shared meta ───────────────────────────────────────────────────────────────

export const KIND_META: Record<CategoryOut['kind'], { label: string; bg: string; text: string }> = {
  EXPENSE: { label: 'Despesa', bg: 'bg-red-500/10', text: 'text-red-600 dark:text-red-400' },
  INCOME: { label: 'Renda', bg: 'bg-emerald-500/10', text: 'text-emerald-600 dark:text-emerald-400' },
  TRANSFER: { label: 'Transferência', bg: 'bg-indigo-500/10', text: 'text-indigo-600 dark:text-indigo-300' },
}

export const PARTY_KIND_META: Record<PartyOut['kind'], string> = {
  SUPPLIER: 'Fornecedor',
  CLIENT: 'Cliente',
  BOTH: 'Ambos',
}

export function KindBadge({ kind }: { kind: CategoryOut['kind'] }) {
  const m = KIND_META[kind]
  return (
    <span className={`inline-flex items-center px-1.5 py-0.5 rounded-md text-[10px] font-medium uppercase tracking-wider ${m.bg} ${m.text}`}>
      {m.label}
    </span>
  )
}

/** Agrupa categorias em raízes + filhas (1 nível), ordenadas por nome. */
export function groupCategories(cats: CategoryOut[]): Array<{ root: CategoryOut; children: CategoryOut[] }> {
  const roots = cats.filter(c => c.parent_id === null).sort((a, b) => a.name.localeCompare(b.name))
  return roots.map(root => ({
    root,
    children: cats.filter(c => c.parent_id === root.id).sort((a, b) => a.name.localeCompare(b.name)),
  }))
}

// ── category modal ────────────────────────────────────────────────────────────

interface CategoryModalProps {
  initial?: CategoryOut
  parent?: CategoryOut       // set → creating/editing a subcategory
  onSave: (data: { name: string; parent_id?: string | null; kind?: string | null; color?: string | null }) => Promise<void>
  onClose: () => void
}

function CategoryModal({ initial, parent, onSave, onClose }: CategoryModalProps) {
  const [name, setName] = useState(initial?.name ?? '')
  const [kind, setKind] = useState<CategoryOut['kind']>(initial?.kind ?? parent?.kind ?? 'EXPENSE')
  const [color, setColor] = useState(initial?.color ?? parent?.color ?? '#6366f1')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const isSub = !!parent || !!initial?.parent_id

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    setSaving(true)
    try {
      await onSave({
        name,
        parent_id: parent?.id ?? initial?.parent_id ?? null,
        kind: isSub ? null : kind,
        color,
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
          {initial ? 'Editar categoria' : parent ? `Nova subcategoria de ${parent.name}` : 'Nova categoria'}
        </h2>
        <form onSubmit={handleSubmit} className="space-y-3">
          <Field label="Nome">
            <input type="text" value={name} onChange={e => setName(e.target.value)} required className={INPUT_CLS} />
          </Field>
          {!isSub && (
            <Field label="Tipo">
              <select value={kind} onChange={e => setKind(e.target.value as CategoryOut['kind'])} className={INPUT_CLS}>
                <option value="EXPENSE">Despesa</option>
                <option value="INCOME">Renda</option>
                <option value="TRANSFER">Transferência</option>
              </select>
            </Field>
          )}
          <Field label="Cor">
            <input type="color" value={color} onChange={e => setColor(e.target.value)} className="h-9 w-16 rounded cursor-pointer bg-transparent" />
          </Field>
          {error && <p className="text-[12px] text-red-500 dark:text-red-400">{error}</p>}
          <div className="flex justify-end gap-2 pt-2">
            <button type="button" onClick={onClose} className="h-9 px-4 inline-flex items-center rounded-lg text-[12px] text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors">Cancelar</button>
            <button type="submit" disabled={saving} className="h-9 px-4 inline-flex items-center rounded-lg bg-indigo-500 hover:bg-indigo-400 disabled:opacity-60 text-white text-[12px] font-medium transition-colors">
              {saving ? 'Salvando…' : 'Salvar'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

// ── party modal ───────────────────────────────────────────────────────────────

interface PartyModalProps {
  initial?: PartyOut
  onSave: (data: { name: string; kind: string; notes: string | null }) => Promise<void>
  onClose: () => void
}

function PartyModal({ initial, onSave, onClose }: PartyModalProps) {
  const [name, setName] = useState(initial?.name ?? '')
  const [kind, setKind] = useState<PartyOut['kind']>(initial?.kind ?? 'SUPPLIER')
  const [notes, setNotes] = useState(initial?.notes ?? '')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    setSaving(true)
    try {
      await onSave({ name, kind, notes: notes.trim() || null })
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
          {initial ? 'Editar fornecedor/cliente' : 'Novo fornecedor/cliente'}
        </h2>
        <form onSubmit={handleSubmit} className="space-y-3">
          <Field label="Nome">
            <input type="text" value={name} onChange={e => setName(e.target.value)} required placeholder="Ex: Pão de Açúcar" className={INPUT_CLS} />
          </Field>
          <Field label="Tipo">
            <select value={kind} onChange={e => setKind(e.target.value as PartyOut['kind'])} className={INPUT_CLS}>
              <option value="SUPPLIER">Fornecedor</option>
              <option value="CLIENT">Cliente</option>
              <option value="BOTH">Ambos</option>
            </select>
          </Field>
          <Field label="Notas (opcional)">
            <input type="text" value={notes} onChange={e => setNotes(e.target.value)} className={INPUT_CLS} />
          </Field>
          {error && <p className="text-[12px] text-red-500 dark:text-red-400">{error}</p>}
          <div className="flex justify-end gap-2 pt-2">
            <button type="button" onClick={onClose} className="h-9 px-4 inline-flex items-center rounded-lg text-[12px] text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors">Cancelar</button>
            <button type="submit" disabled={saving} className="h-9 px-4 inline-flex items-center rounded-lg bg-indigo-500 hover:bg-indigo-400 disabled:opacity-60 text-white text-[12px] font-medium transition-colors">
              {saving ? 'Salvando…' : 'Salvar'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

// ── page ──────────────────────────────────────────────────────────────────────

type TabKey = 'categories' | 'parties' | 'tags'

export default function Registry() {
  const navigate = useNavigate()
  const [me, setMe] = useState<UserOut | null>(null)
  const [tab, setTab] = useState<TabKey>('categories')

  const [categories, setCategories] = useState<CategoryOut[]>([])
  const [parties, setParties] = useState<PartyOut[]>([])
  const [tags, setTags] = useState<TagOut[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')

  // category modal state
  const [catModal, setCatModal] = useState<{ initial?: CategoryOut; parent?: CategoryOut } | null>(null)
  // party modal state
  const [partyModal, setPartyModal] = useState<{ initial?: PartyOut } | null>(null)
  const [partySearch, setPartySearch] = useState('')
  // merge mode: id of the first selected party (the SOURCE candidate)
  const [mergeFirst, setMergeFirst] = useState<string | null>(null)
  const [mergePair, setMergePair] = useState<{ a: PartyOut; b: PartyOut } | null>(null)
  // tag inline state
  const [newTag, setNewTag] = useState('')
  const [renamingTag, setRenamingTag] = useState<TagOut | null>(null)
  const [renameValue, setRenameValue] = useState('')
  const [actionError, setActionError] = useState('')

  useEscapeKey(() => {
    if (mergePair) setMergePair(null)
    else if (catModal) setCatModal(null)
    else if (partyModal) setPartyModal(null)
    else if (renamingTag) setRenamingTag(null)
    else if (mergeFirst) setMergeFirst(null)
  })

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
    Promise.all([api.listCategories(), api.listParties(), api.listTags()])
      .then(([cats, ps, ts]) => {
        setCategories(cats)
        setParties(ps)
        setTags(ts)
      })
      .catch(err => setLoadError(err instanceof Error ? err.message : 'Erro ao carregar.'))
      .finally(() => setLoading(false))
  }, [me])

  const canWrite = me?.role === 'admin' || me?.role === 'sysadmin'
  const grouped = useMemo(() => groupCategories(categories), [categories])
  const filteredParties = useMemo(() => {
    const q = partySearch.trim().toLowerCase()
    if (!q) return parties
    return parties.filter(p => p.name.toLowerCase().includes(q))
  }, [parties, partySearch])

  async function refreshCategories() {
    setCategories(await api.listCategories())
  }

  async function refreshParties() {
    setParties(await api.listParties())
  }

  async function handleMerge(survivor: PartyOut, source: PartyOut) {
    setActionError('')
    try {
      await api.mergeParty(survivor.id, source.id)
      setMergePair(null)
      setMergeFirst(null)
      await refreshParties()
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Erro ao mesclar.')
    }
  }

  if (!me) return null

  const TABS: Array<{ key: TabKey; label: string; count: number }> = [
    { key: 'categories', label: 'Categorias', count: categories.length },
    { key: 'parties', label: 'Fornecedores/Clientes', count: parties.length },
    { key: 'tags', label: 'Tags', count: tags.length },
  ]

  return (
    <AppLayout user={me}>
      <div className="space-y-6">
        <PageHeader
          title="Cadastros"
          count={categories.length + parties.length + tags.length}
          countLabel="itens de cadastro do lado despesas"
        />

        <div className="flex items-center gap-1 border-b border-gray-200 dark:border-gray-800">
          {TABS.map(t => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={`px-3 py-2 text-[12px] font-medium border-b-2 -mb-px transition-colors ${
                tab === t.key
                  ? 'border-indigo-500 text-indigo-600 dark:text-indigo-400'
                  : 'border-transparent text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'
              }`}
            >
              {t.label} <span className="text-gray-400 dark:text-gray-600 tnum">{t.count}</span>
            </button>
          ))}
        </div>

        {loadError ? (
          <Card><div className="text-sm text-red-600 dark:text-red-400 text-center py-6">{loadError}</div></Card>
        ) : loading ? (
          <Card><div className="text-sm text-gray-400 dark:text-gray-600 text-center py-12">Carregando…</div></Card>
        ) : tab === 'categories' ? (
          <Card>
            <div className="flex items-center justify-between mb-3">
              <span className="text-[11px] uppercase tracking-wider text-gray-500">Árvore de categorias</span>
              {canWrite && (
                <button onClick={() => setCatModal({})} className="h-8 px-3 inline-flex items-center gap-1.5 rounded-lg text-[12px] bg-indigo-500 hover:bg-indigo-400 text-white transition-colors">
                  <Plus className="w-3.5 h-3.5" /> Nova categoria
                </button>
              )}
            </div>
            {grouped.length === 0 ? (
              <div className="text-[11px] text-gray-400 dark:text-gray-600 text-center py-6">Nenhuma categoria.</div>
            ) : (
              <div className="space-y-1">
                {grouped.map(({ root, children }) => (
                  <div key={root.id}>
                    <div className="flex items-center gap-2 px-2 py-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800/40 group">
                      <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ background: root.color ?? '#6b7280' }} />
                      <span className="text-[13px] font-medium text-gray-900 dark:text-white flex-1">{root.name}</span>
                      <KindBadge kind={root.kind} />
                      {canWrite && (
                        <span className="opacity-0 group-hover:opacity-100 flex items-center gap-1 transition-opacity">
                          <button title="Nova subcategoria" onClick={() => setCatModal({ parent: root })} className="p-1 rounded text-gray-500 hover:text-indigo-500"><Plus className="w-3.5 h-3.5" /></button>
                          <button title="Editar" onClick={() => setCatModal({ initial: root })} className="p-1 rounded text-gray-500 hover:text-indigo-500"><Pencil className="w-3 h-3" /></button>
                          <button title="Desativar" onClick={() => api.deactivateCategory(root.id).then(refreshCategories).catch(err => setActionError(err.message))} className="p-1 rounded text-gray-500 hover:text-red-500"><X className="w-3.5 h-3.5" /></button>
                        </span>
                      )}
                    </div>
                    {children.map(c => (
                      <div key={c.id} className="flex items-center gap-2 pl-8 pr-2 py-1 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800/40 group">
                        <span className="w-2 h-2 rounded-full shrink-0" style={{ background: c.color ?? '#6b7280' }} />
                        <span className="text-[12px] text-gray-700 dark:text-gray-300 flex-1">{c.name}</span>
                        {canWrite && (
                          <span className="opacity-0 group-hover:opacity-100 flex items-center gap-1 transition-opacity">
                            <button title="Editar" onClick={() => setCatModal({ initial: c })} className="p-1 rounded text-gray-500 hover:text-indigo-500"><Pencil className="w-3 h-3" /></button>
                            <button title="Desativar" onClick={() => api.deactivateCategory(c.id).then(refreshCategories).catch(err => setActionError(err.message))} className="p-1 rounded text-gray-500 hover:text-red-500"><X className="w-3.5 h-3.5" /></button>
                          </span>
                        )}
                      </div>
                    ))}
                  </div>
                ))}
              </div>
            )}
          </Card>
        ) : tab === 'parties' ? (
          <Card>
            <div className="flex items-center justify-between gap-3 mb-3 flex-wrap">
              <input
                type="text"
                value={partySearch}
                onChange={e => setPartySearch(e.target.value)}
                placeholder="Buscar…"
                className={`${INPUT_CLS} max-w-[220px]`}
              />
              {canWrite && (
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => { setMergeFirst(mergeFirst === null ? '' : null) }}
                    className={`h-8 px-3 inline-flex items-center gap-1.5 rounded-lg text-[12px] transition-colors ${
                      mergeFirst !== null
                        ? 'bg-amber-500/15 text-amber-600 dark:text-amber-400'
                        : 'bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700'
                    }`}
                  >
                    <GitMerge className="w-3.5 h-3.5" /> {mergeFirst !== null ? 'Selecionando… (ESC cancela)' : 'Mesclar'}
                  </button>
                  <button onClick={() => setPartyModal({})} className="h-8 px-3 inline-flex items-center gap-1.5 rounded-lg text-[12px] bg-indigo-500 hover:bg-indigo-400 text-white transition-colors">
                    <Plus className="w-3.5 h-3.5" /> Novo
                  </button>
                </div>
              )}
            </div>
            {filteredParties.length === 0 ? (
              <div className="text-[11px] text-gray-400 dark:text-gray-600 text-center py-6">
                {parties.length === 0 ? 'Nenhum fornecedor/cliente — o import de extrato (spec 71) cria automaticamente.' : 'Nada encontrado.'}
              </div>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-1">
                {filteredParties.map(p => {
                  const selected = mergeFirst === p.id
                  return (
                    <div
                      key={p.id}
                      role={mergeFirst !== null ? 'button' : undefined}
                      onClick={() => {
                        if (mergeFirst === null) return
                        if (mergeFirst === '') { setMergeFirst(p.id); return }
                        if (mergeFirst === p.id) { setMergeFirst(''); return }
                        const a = parties.find(x => x.id === mergeFirst)
                        if (a) setMergePair({ a, b: p })
                      }}
                      className={`flex items-center gap-2 px-2 py-1.5 rounded-lg transition-colors ${
                        selected ? 'bg-amber-500/15 ring-1 ring-amber-400' : 'hover:bg-gray-100 dark:hover:bg-gray-800/40'
                      } ${mergeFirst !== null ? 'cursor-pointer' : ''} group`}
                    >
                      <span className="text-[13px] text-gray-900 dark:text-white flex-1 truncate">{p.name}</span>
                      <span className="text-[10px] uppercase tracking-wider text-gray-500">{PARTY_KIND_META[p.kind]}</span>
                      {p.alias_count > 0 && <span className="text-[10px] text-gray-500 tnum">{p.alias_count} alias</span>}
                      {canWrite && mergeFirst === null && (
                        <span className="opacity-0 group-hover:opacity-100 flex items-center gap-1 transition-opacity">
                          <button title="Editar" onClick={() => setPartyModal({ initial: p })} className="p-1 rounded text-gray-500 hover:text-indigo-500"><Pencil className="w-3 h-3" /></button>
                          <button title="Desativar" onClick={() => api.deactivateParty(p.id).then(refreshParties).catch(err => setActionError(err.message))} className="p-1 rounded text-gray-500 hover:text-red-500"><X className="w-3.5 h-3.5" /></button>
                        </span>
                      )}
                    </div>
                  )
                })}
              </div>
            )}
          </Card>
        ) : (
          <Card>
            {canWrite && (
              <form
                onSubmit={async e => {
                  e.preventDefault()
                  if (!newTag.trim()) return
                  setActionError('')
                  try {
                    await api.createTag(newTag)
                    setNewTag('')
                    setTags(await api.listTags())
                  } catch (err) {
                    setActionError(err instanceof Error ? err.message : 'Erro ao criar tag.')
                  }
                }}
                className="flex items-center gap-2 mb-4"
              >
                <input type="text" value={newTag} onChange={e => setNewTag(e.target.value)} placeholder="nova-tag" className={`${INPUT_CLS} max-w-[220px]`} />
                <button type="submit" className="h-9 px-3 inline-flex items-center gap-1.5 rounded-lg text-[12px] bg-indigo-500 hover:bg-indigo-400 text-white transition-colors">
                  <Plus className="w-3.5 h-3.5" /> Criar
                </button>
              </form>
            )}
            {tags.length === 0 ? (
              <div className="text-[11px] text-gray-400 dark:text-gray-600 text-center py-6">Nenhuma tag.</div>
            ) : (
              <div className="flex flex-wrap gap-2">
                {tags.map(t => (
                  <span key={t.id} className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[12px] bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300">
                    {t.name}
                    {canWrite && (
                      <>
                        <button title="Renomear" onClick={() => { setRenamingTag(t); setRenameValue(t.name) }} className="text-gray-500 hover:text-indigo-500"><Pencil className="w-3 h-3" /></button>
                        <button
                          title="Excluir"
                          onClick={() => api.deleteTag(t.id).then(() => setTags(prev => prev.filter(x => x.id !== t.id))).catch(err => setActionError(err.message))}
                          className="text-gray-500 hover:text-red-500"
                        ><X className="w-3 h-3" /></button>
                      </>
                    )}
                  </span>
                ))}
              </div>
            )}
          </Card>
        )}

        {actionError && (
          <div className="fixed bottom-4 right-4 z-[70] max-w-sm bg-red-600 text-white text-[12px] rounded-lg shadow-lg px-4 py-3 flex items-start gap-3">
            <span className="flex-1">{actionError}</span>
            <button onClick={() => setActionError('')} className="shrink-0 hover:opacity-70"><X className="w-3.5 h-3.5" /></button>
          </div>
        )}
      </div>

      {catModal && (
        <CategoryModal
          initial={catModal.initial}
          parent={catModal.parent}
          onSave={async data => {
            if (catModal.initial) {
              await api.updateCategory(catModal.initial.id, { name: data.name, color: data.color, kind: catModal.initial.parent_id ? undefined : data.kind ?? undefined })
            } else {
              await api.createCategory(data)
            }
            await refreshCategories()
          }}
          onClose={() => setCatModal(null)}
        />
      )}

      {partyModal && (
        <PartyModal
          initial={partyModal.initial}
          onSave={async data => {
            if (partyModal.initial) await api.updateParty(partyModal.initial.id, data)
            else await api.createParty(data)
            await refreshParties()
          }}
          onClose={() => setPartyModal(null)}
        />
      )}

      {renamingTag && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/40">
          <div className="w-full max-w-sm bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-700 shadow-xl p-6">
            <h2 className="text-base font-semibold text-gray-900 dark:text-white mb-4">Renomear tag</h2>
            <form
              onSubmit={async e => {
                e.preventDefault()
                setActionError('')
                try {
                  await api.renameTag(renamingTag.id, renameValue)
                  setRenamingTag(null)
                  setTags(await api.listTags())
                } catch (err) {
                  setActionError(err instanceof Error ? err.message : 'Erro ao renomear.')
                }
              }}
              className="space-y-4"
            >
              <input type="text" value={renameValue} onChange={e => setRenameValue(e.target.value)} required autoFocus className={INPUT_CLS} />
              <div className="flex justify-end gap-2">
                <button type="button" onClick={() => setRenamingTag(null)} className="h-9 px-4 inline-flex items-center rounded-lg text-[12px] text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors">Cancelar</button>
                <button type="submit" className="h-9 px-4 inline-flex items-center rounded-lg bg-indigo-500 hover:bg-indigo-400 text-white text-[12px] font-medium transition-colors">Salvar</button>
              </div>
            </form>
          </div>
        </div>
      )}

      {mergePair && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/40">
          <div className="w-full max-w-md bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-700 shadow-xl p-6">
            <h2 className="text-base font-semibold text-gray-900 dark:text-white mb-2">Mesclar fornecedores/clientes</h2>
            <p className="text-sm text-gray-500 dark:text-gray-400 mb-4">
              Escolha o <strong>sobrevivente</strong> — o outro será removido e todas as referências (aliases, transações) passam pra ele.
            </p>
            <div className="space-y-2 mb-4">
              {[{ survivor: mergePair.a, source: mergePair.b }, { survivor: mergePair.b, source: mergePair.a }].map(({ survivor, source }) => (
                <button
                  key={survivor.id}
                  onClick={() => handleMerge(survivor, source)}
                  className="w-full text-left px-3 py-2.5 rounded-lg border border-gray-200 dark:border-gray-700 hover:border-indigo-500 hover:bg-indigo-500/5 transition-colors"
                >
                  <span className="text-[13px] font-medium text-gray-900 dark:text-white">{survivor.name}</span>
                  <span className="text-[11px] text-gray-500 block">absorve “{source.name}”</span>
                </button>
              ))}
            </div>
            <div className="flex justify-end">
              <button onClick={() => setMergePair(null)} className="px-4 py-2 rounded-lg text-sm text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors">Cancelar</button>
            </div>
          </div>
        </div>
      )}
    </AppLayout>
  )
}
