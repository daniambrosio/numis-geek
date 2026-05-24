import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { ExternalLink, Plus } from 'lucide-react'
import {
  api, type AssetOut, type AssetRequest, type FinancialInstitutionOut,
  type PositionOut, type UserOut,
} from '../../lib/api'
import AppLayout from '../../components/AppLayout'
import AssetModal from '../../components/AssetModal'
import AssetTable from '../../components/AssetTable'
import {
  Card, PageHeader, SearchInput, ToggleSwitch, MultiChips, FilterGroup,
  GroupingToggle,
} from '../../components/ui'
import { KLASS, collapsedOf, fiTokenFor, type CollapsedClassCode } from '../../lib/tokens'

type Grouping = 'none' | 'klass' | 'fi'

const KLASS_OPTS = (Object.keys(KLASS) as CollapsedClassCode[]).map(id => ({
  id,
  label: KLASS[id].label,
  color: KLASS[id].color,
}))

const COUNTRY_OPTS = [
  { id: 'BR', label: '🇧🇷 Brasil' },
  { id: 'US', label: '🇺🇸 EUA' },
]

const GROUPING_OPTS = [
  { id: 'none', label: 'Sem grupo' },
  { id: 'klass', label: 'Classe' },
  { id: 'fi', label: 'Custodiante' },
]

export default function Assets() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const [me, setMe] = useState<UserOut | null>(null)
  const [assets, setAssets] = useState<AssetOut[]>([])
  const [institutions, setInstitutions] = useState<FinancialInstitutionOut[]>([])
  const [positions, setPositions] = useState<Map<string, PositionOut | null>>(new Map())
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<AssetOut | undefined>(undefined)
  const [confirmDeactivate, setConfirmDeactivate] = useState<AssetOut | null>(null)

  // filters
  const [search, setSearch] = useState('')
  const [klassSel, setKlassSel] = useState<string[]>([])
  const [countrySel, setCountrySel] = useState<string[]>([])
  const [fiSel, setFiSel] = useState<string[]>([])
  const [includeInactive, setIncludeInactive] = useState(false)
  const [grouping, setGrouping] = useState<Grouping>('none')

  useEffect(() => {
    api.me()
      .then(u => {
        if (u.role === 'sysadmin') {
          navigate('/sysadmin/assets')
          return
        }
        setMe(u)
      })
      .catch(() => navigate('/login'))
  }, [navigate])

  // Open AssetModal when launched via "Novo → Ativo" from the top bar.
  useEffect(() => {
    if (searchParams.get('compose') === 'asset') {
      setEditing(undefined)
      setModalOpen(true)
      const next = new URLSearchParams(searchParams)
      next.delete('compose')
      setSearchParams(next, { replace: true })
    }
  }, [searchParams, setSearchParams])

  useEffect(() => {
    if (!me) return
    setLoading(true)
    setLoadError('')
    Promise.all([
      api.listAssets({
        include_inactive: includeInactive,
        search: search.trim() || undefined,
      }),
      api.listFinancialInstitutions(),
    ])
      .then(([as, fis]) => {
        setAssets(as)
        setInstitutions(fis)
        setPositions(new Map())
        // Kick off position fetches; update map as each resolves.
        for (const a of as) {
          api.getAssetPosition(a.id)
            .then(p => setPositions(prev => {
              const next = new Map(prev)
              next.set(a.id, p)
              return next
            }))
            .catch(() => setPositions(prev => {
              const next = new Map(prev)
              next.set(a.id, null)
              return next
            }))
        }
      })
      .catch(err => setLoadError(err instanceof Error ? err.message : 'Erro ao carregar.'))
      .finally(() => setLoading(false))
  }, [me, includeInactive, search])

  // Client-side filters: class (collapsed) + custodian. Country deferred (spec 09).
  const filtered = useMemo(() => {
    let xs = assets
    if (klassSel.length) {
      xs = xs.filter(a => klassSel.includes(collapsedOf(a.asset_class)))
    }
    if (countrySel.length) {
      xs = xs.filter(a => countrySel.includes(a.country))
    }
    if (fiSel.length) {
      xs = xs.filter(a => fiSel.includes(a.financial_institution_id))
    }
    return xs
  }, [assets, klassSel, countrySel, fiSel])

  const fiOpts = useMemo(() => {
    const present = new Set(assets.map(a => a.financial_institution_id))
    return institutions
      .filter(fi => present.has(fi.id))
      .map(fi => ({ id: fi.id, label: fi.short_name, color: fiTokenFor(fi.logo_slug, fi.short_name).color }))
  }, [assets, institutions])

  const stats = useMemo(() => {
    const classes = new Set(filtered.map(a => collapsedOf(a.asset_class))).size
    const custos = new Set(filtered.map(a => a.financial_institution_id)).size
    return { classes, custos }
  }, [filtered])

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
      <div className="space-y-6">
        <PageHeader
          title="Ativos"
          count={filtered.length}
          countLabel={`ativos · ${stats.classes} ${stats.classes === 1 ? 'classe' : 'classes'} · ${stats.custos} ${stats.custos === 1 ? 'custodiante' : 'custodiantes'}`}
          action={
            <div className="flex items-center gap-2">
              <button
                disabled
                title="Em breve"
                className="h-8 px-3 inline-flex items-center gap-1.5 rounded-lg text-[12px] bg-gray-100 dark:bg-gray-800 text-gray-400 dark:text-gray-600 cursor-not-allowed"
              >
                <ExternalLink className="w-3.5 h-3.5" /> Exportar
              </button>
              <button
                onClick={() => { setEditing(undefined); setModalOpen(true) }}
                className="h-8 px-3 inline-flex items-center gap-1.5 rounded-lg text-[12px] bg-indigo-500 hover:bg-indigo-400 text-white transition-colors"
              >
                <Plus className="w-3.5 h-3.5" /> Novo ativo
              </button>
            </div>
          }
        />

        <Card padding="p-3" className="space-y-3">
          <div className="flex items-center gap-3 flex-wrap">
            <SearchInput
              value={search}
              onChange={setSearch}
              placeholder="Buscar por ticker ou nome…"
              className="w-64"
            />
            <div className="flex-1" />
            <ToggleSwitch on={includeInactive} onChange={setIncludeInactive} label="Incluir zerados" />
          </div>
          <div className="space-y-2 pt-3 border-t border-gray-200 dark:border-gray-800">
            <FilterGroup label="Classe">
              <MultiChips options={KLASS_OPTS} selected={klassSel} onChange={setKlassSel} />
            </FilterGroup>
            <FilterGroup label="País">
              <MultiChips options={COUNTRY_OPTS} selected={countrySel} onChange={setCountrySel} />
            </FilterGroup>
            <FilterGroup label="Custodiante">
              <MultiChips options={fiOpts} selected={fiSel} onChange={setFiSel} />
            </FilterGroup>
          </div>
          <div className="flex items-center gap-3 pt-3 border-t border-gray-200 dark:border-gray-800 flex-wrap">
            <span className="text-[10px] uppercase tracking-wider text-gray-500 dark:text-gray-400 font-medium min-w-[90px]">
              Agrupar por
            </span>
            <GroupingToggle value={grouping} onChange={v => setGrouping(v as Grouping)} options={GROUPING_OPTS} />
            <div className="flex-1" />
            <div className="text-[11px] text-gray-500 dark:text-gray-400">
              <span className="tnum">{filtered.length}</span> de <span className="tnum">{assets.length}</span> ativos
            </div>
          </div>
        </Card>

        {loadError ? (
          <Card>
            <div className="text-sm text-red-600 dark:text-red-400 text-center py-6">{loadError}</div>
          </Card>
        ) : loading ? (
          <Card>
            <div className="text-sm text-gray-400 dark:text-gray-600 text-center py-12">Carregando…</div>
          </Card>
        ) : (
          <AssetTable
            assets={filtered}
            positions={positions}
            institutions={institutions}
            grouping={grouping}
            onRowClick={(a) => navigate(`/assets/${a.id}`)}
            onAssetUpdated={(updated) =>
              setAssets(prev => prev.map(a => a.id === updated.id ? updated : a))
            }
          />
        )}
      </div>

      {modalOpen && institutions.length > 0 && (
        <AssetModal
          initial={editing}
          institutions={institutions}
          onSave={handleSave}
          onClose={() => { setModalOpen(false); setEditing(undefined) }}
        />
      )}

      {confirmDeactivate && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/40">
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
