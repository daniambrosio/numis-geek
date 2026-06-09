import { Fragment, useEffect, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Plus } from 'lucide-react'
import {
  api,
  type AssetOut,
  type FinancialInstitutionOut,
  type AssetMovementOut,
  type AssetMovementRequest,
  type AssetMovementType,
  type UserOut,
  ASSET_MOVEMENT_TYPE_LABELS,
} from '../lib/api'
import AppLayout from '../components/AppLayout'
import AffectedSnapshotsModal from '../components/AffectedSnapshotsModal'
import MovementComposer from '../components/MovementComposer'
import LancamentoDetailPanel from '../components/LancamentoDetailPanel'
import OptionModal from '../components/OptionModal'
import { type AttachmentDraft, type PersistedAttachment } from '../components/NotesAttachmentsField'
import { useEscapeKey } from '../lib/useEscapeKey'
import type { AffectedSnapshotOut } from '../lib/api'
import {
  Card, PageHeader, SearchInput, ToggleSwitch, MultiChips, FilterGroup,
  QuickAddBar, TypeBadge,
} from '../components/ui'
import { KLASS, collapsedOf, lanTypeColor } from '../lib/tokens'

const TYPE_ORDER: AssetMovementType[] = [
  'BUY', 'SELL', 'SELL_OPEN', 'BONUS', 'SUBSCRIPTION', 'COME_COTAS',
  'FULL_REDEMPTION',
]

const TYPE_OPTS = TYPE_ORDER.map(t => ({
  id: t,
  label: ASSET_MOVEMENT_TYPE_LABELS[t],
  color: lanTypeColor(t),
}))

const MONTH_NAMES = [
  'Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho',
  'Julho', 'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro',
]

function fmtMoney(n: number | null | undefined, currency: string, opts: { sign?: boolean; compact?: boolean } = {}) {
  if (n == null) return '—'
  const v = opts.sign ? Math.abs(n) : n
  const sign = opts.sign && n > 0 ? '+ ' : opts.sign && n < 0 ? '− ' : ''
  const symbol = currency === 'USD' ? 'US$' : 'R$'
  if (opts.compact && Math.abs(v) >= 1_000_000) {
    return sign + `${symbol} ${(v / 1_000_000).toFixed(1).replace('.', ',')}M`
  }
  if (opts.compact && Math.abs(v) >= 1000) {
    return sign + `${symbol} ${(v / 1000).toFixed(1).replace('.', ',')}k`
  }
  return sign + v.toLocaleString('pt-BR', { style: 'currency', currency })
}

function fmtNum(n: number | null | undefined, digits = 8) {
  if (n == null) return '—'
  return n.toLocaleString('pt-BR', { maximumFractionDigits: digits })
}

function fmtBRL(n: number, opts: { sign?: boolean; compact?: boolean } = {}) {
  return fmtMoney(n, 'BRL', opts)
}

function fmtDate(iso: string): string {
  return new Intl.DateTimeFormat('pt-BR').format(new Date(iso + 'T00:00:00'))
}

export default function AssetMovements() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const [me, setMe] = useState<UserOut | null>(null)
  const [items, setItems] = useState<AssetMovementOut[]>([])
  const [assets, setAssets] = useState<AssetOut[]>([])
  const [institutions, setInstitutions] = useState<FinancialInstitutionOut[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [modalOpen, setModalOpen] = useState(false)
  const [optionModalOpen, setOptionModalOpen] = useState(false)
  const [editing, setEditing] = useState<AssetMovementOut | undefined>(undefined)
  const [editingAttachments, setEditingAttachments] = useState<PersistedAttachment[]>([])
  const [confirmDeactivate, setConfirmDeactivate] = useState<AssetMovementOut | null>(null)
  const [selected, setSelected] = useState<AssetMovementOut | null>(null)
  // Spec 51 — Retroactive Event Reconciliation
  const [reconciliation, setReconciliation] = useState<{
    affected: AffectedSnapshotOut[]
    assetId: string
    assetLabel: string
    triggerEventId: string
    triggerEventType: string
  } | null>(null)
  // Sub-modals (MovementComposer/OptionModal/LancamentoDetailPanel) already
  // handle ESC internally; this hook covers only the inline confirm dialog.
  useEscapeKey(() => { if (confirmDeactivate) setConfirmDeactivate(null) })

  // Filters
  const [search, setSearch] = useState('')
  const [typesSel, setTypesSel] = useState<string[]>([])
  const [fromDate, setFromDate] = useState('')
  const [toDate, setToDate] = useState('')
  const [includeInactive, setIncludeInactive] = useState(false)

  useEffect(() => {
    api.me().then(setMe).catch(() => navigate('/login'))
  }, [navigate])

  // Open MovementComposer when launched via "Novo → Lançamento" from the top bar.
  // Open OptionModal when launched via "Novo → Opção" (Spec 36).
  useEffect(() => {
    const compose = searchParams.get('compose')
    if (compose === 'movement') {
      setEditing(undefined)
      setModalOpen(true)
      const next = new URLSearchParams(searchParams)
      next.delete('compose')
      setSearchParams(next, { replace: true })
    } else if (compose === 'option') {
      setOptionModalOpen(true)
      const next = new URLSearchParams(searchParams)
      next.delete('compose')
      setSearchParams(next, { replace: true })
    }
  }, [searchParams, setSearchParams])

  useEffect(() => {
    if (!me) return
    setLoading(true)
    setLoadError('')
    const lanParams = {
      type: (typesSel.length === 1 ? (typesSel[0] as AssetMovementType) : undefined),
      from: fromDate || undefined,
      to: toDate || undefined,
      include_inactive: includeInactive,
      page_size: 200,
    }

    Promise.all([
      api.listAssetMovements({ ...lanParams, page: 1 }),
      api.listAssets({ include_inactive: true }),
      api.listFinancialInstitutions(),
    ])
      .then(async ([firstPage, as, fis]) => {
        setAssets(as)
        setInstitutions(fis)
        // Fetch remaining pages if total exceeds first page (backend caps page_size at 200).
        const totalPages = Math.ceil(firstPage.total / firstPage.page_size)
        if (totalPages <= 1) {
          setItems(firstPage.items)
          return
        }
        const rest = await Promise.all(
          Array.from({ length: totalPages - 1 }, (_, i) =>
            api.listAssetMovements({ ...lanParams, page: i + 2 }),
          ),
        )
        const all = firstPage.items.concat(...rest.map(p => p.items))
        setItems(all)
      })
      .catch(err => setLoadError(err instanceof Error ? err.message : 'Erro ao carregar.'))
      .finally(() => setLoading(false))
  }, [me, typesSel, fromDate, toDate, includeInactive])

  const assetById = useMemo(() => {
    const m = new Map<string, AssetOut>()
    for (const a of assets) m.set(a.id, a)
    return m
  }, [assets])
  const fiById = useMemo(() => {
    const m = new Map<string, FinancialInstitutionOut>()
    for (const fi of institutions) m.set(fi.id, fi)
    return m
  }, [institutions])

  // Client-side filters: multi-type, search.
  const filtered = useMemo(() => {
    let xs = items
    if (typesSel.length > 1) xs = xs.filter(x => typesSel.includes(x.type))
    if (search.trim()) {
      const q = search.trim().toLowerCase()
      xs = xs.filter(l => {
        const a = assetById.get(l.asset_id)
        return (a?.ticker || '').toLowerCase().includes(q) || (a?.name || '').toLowerCase().includes(q)
      })
    }
    return xs
  }, [items, typesSel, search, assetById])

  const sorted = useMemo(
    () => [...filtered].sort((a, b) => b.event_date.localeCompare(a.event_date)),
    [filtered],
  )

  // Group by Year-Month
  const grouped = useMemo(() => {
    const m = new Map<string, AssetMovementOut[]>()
    for (const it of sorted) {
      const ym = it.event_date.slice(0, 7) // YYYY-MM
      if (!m.has(ym)) m.set(ym, [])
      m.get(ym)!.push(it)
    }
    return Array.from(m.entries()).map(([ym, arr]) => ({ ym, items: arr }))
  }, [sorted])

  const stats = useMemo(() => {
    const totalNet = sorted.reduce((s, l) => {
      const fx = Number(l.fx_rate) || 1
      return s + Number(l.net_amount) * fx
    }, 0)
    const uniqAssets = new Set(sorted.map(l => l.asset_id)).size
    return { totalNet, count: sorted.length, uniqAssets }
  }, [sorted])

  async function handleSave(data: AssetMovementRequest) {
    let saved: AssetMovementOut
    const isUpdate = !!editing
    if (editing) {
      saved = await api.updateAssetMovement(editing.id, data)
      setItems(prev => prev.map(l => l.id === saved.id ? saved : l))
      if (selected?.id === saved.id) setSelected(saved)
    } else {
      saved = await api.createAssetMovement(data)
      setItems(prev => [saved, ...prev])
    }
    // Spec 51 — depois do save, sonda fechamentos afetados; se houver,
    // abre o AffectedSnapshotsModal. Não bloqueia o save.
    try {
      const affected = await api.previewAffectedSnapshots(
        saved.asset_id, saved.event_date,
      )
      if (affected.length > 0) {
        setReconciliation({
          affected,
          assetId: saved.asset_id,
          assetLabel: saved.asset_ticker || saved.asset_name,
          triggerEventId: saved.id,
          triggerEventType: isUpdate
            ? 'asset_movement.update'
            : 'asset_movement.create',
        })
      }
    } catch (e) {
      // Preview é best-effort. Falha silenciosa pra não atrapalhar o save.
      console.error('Failed to preview affected snapshots', e)
    }
    return saved
  }

  async function handleCheckImpact(mov: AssetMovementOut) {
    try {
      const affected = await api.previewAffectedSnapshots(
        mov.asset_id, mov.event_date,
      )
      if (affected.length === 0) {
        alert('Nenhum fechamento desincronizado — tudo certo.')
        return
      }
      setReconciliation({
        affected,
        assetId: mov.asset_id,
        assetLabel: mov.asset_ticker || mov.asset_name,
        triggerEventId: mov.id,
        triggerEventType: 'asset_movement.create',
      })
    } catch (e) {
      alert(e instanceof Error ? e.message : 'Erro ao consultar impacto')
    }
  }

  async function handleUploadDrafts(entityId: string, drafts: AttachmentDraft[]) {
    // Upload in parallel; collect failures so the user can retry.
    const results = await Promise.allSettled(
      drafts.map(d => api.uploadAttachment('movement', entityId, d.file)),
    )
    const failed = results
      .map((r, i) => ({ r, name: drafts[i].name }))
      .filter(x => x.r.status === 'rejected')
    if (failed.length) {
      const reason = failed
        .map(x => `${x.name}: ${(x.r as PromiseRejectedResult).reason?.message ?? 'erro desconhecido'}`)
        .join(' · ')
      throw new Error(reason)
    }
  }

  async function handleRemovePersistedAttachment(attachmentId: string) {
    await api.deleteAttachment(attachmentId)
    // Refresh attachments for the currently-edited row.
    if (editing) {
      const list = await api.listAttachments('movement', editing.id)
      setEditingAttachments(list.map(a => ({
        id: a.id, filename: a.filename, size_bytes: a.size_bytes,
        mime_type: a.mime_type, kind: a.kind,
      })))
    }
  }

  async function openEdit(l: AssetMovementOut) {
    setEditing(l)
    setModalOpen(true)
    try {
      const list = await api.listAttachments('movement', l.id)
      setEditingAttachments(list.map(a => ({
        id: a.id, filename: a.filename, size_bytes: a.size_bytes,
        mime_type: a.mime_type, kind: a.kind,
      })))
    } catch {
      // Listing attachments must NOT redirect to login — silently degrade.
      setEditingAttachments([])
    }
  }

  async function handleDeactivate(l: AssetMovementOut) {
    await api.deactivateAssetMovement(l.id)
    if (includeInactive) {
      setItems(prev => prev.map(x => x.id === l.id ? { ...x, is_active: false } : x))
      if (selected?.id === l.id) setSelected({ ...l, is_active: false })
    } else {
      setItems(prev => prev.filter(x => x.id !== l.id))
      if (selected?.id === l.id) setSelected(null)
    }
    setConfirmDeactivate(null)
  }

  if (!me) return null

  return (
    <AppLayout user={me}>
      <div className="space-y-6">
        <PageHeader
          title="Lançamentos"
          count={stats.count}
          countLabel={`movimentações · ${stats.uniqAssets} ${stats.uniqAssets === 1 ? 'ativo' : 'ativos'}`}
          action={
            <div className="flex items-center gap-2">
              <button
                onClick={() => { setEditing(undefined); setModalOpen(true) }}
                disabled={assets.length === 0}
                className="h-8 px-3 inline-flex items-center gap-1.5 rounded-lg text-[12px] bg-indigo-500 hover:bg-indigo-400 disabled:opacity-50 disabled:cursor-not-allowed text-white transition-colors"
              >
                <Plus className="w-3.5 h-3.5" /> Novo Lançamento
              </button>
            </div>
          }
        />

        <QuickAddBar
          placeholder='Lançamento rápido — ex: "compra 100 PETR4 a 38,90 hoje" · em breve'
          onClick={() => { setEditing(undefined); setModalOpen(true) }}
        />

        <Card padding="p-3" className="space-y-3">
          <div className="flex items-center gap-3 flex-wrap">
            <SearchInput
              value={search}
              onChange={setSearch}
              placeholder="Ativo (ticker ou nome)…"
              className="w-64"
            />
            <input
              type="date"
              value={fromDate}
              onChange={e => setFromDate(e.target.value)}
              className="h-8 px-2 text-[12px] rounded-lg bg-gray-100 dark:bg-gray-900 border border-gray-200 dark:border-gray-800 text-gray-700 dark:text-gray-300 focus:outline-none focus:border-indigo-500"
              title="De"
            />
            <span className="text-[10px] text-gray-500">→</span>
            <input
              type="date"
              value={toDate}
              onChange={e => setToDate(e.target.value)}
              className="h-8 px-2 text-[12px] rounded-lg bg-gray-100 dark:bg-gray-900 border border-gray-200 dark:border-gray-800 text-gray-700 dark:text-gray-300 focus:outline-none focus:border-indigo-500"
              title="Até"
            />
            <div className="flex-1" />
            <ToggleSwitch on={includeInactive} onChange={setIncludeInactive} label="Incluir inativos" />
          </div>
          <div className="space-y-2 pt-3 border-t border-gray-200 dark:border-gray-800">
            <FilterGroup label="Tipo">
              <MultiChips options={TYPE_OPTS} selected={typesSel} onChange={setTypesSel} />
            </FilterGroup>
          </div>
          <div className="flex items-center gap-3 pt-3 border-t border-gray-200 dark:border-gray-800 text-[11px] text-gray-500 dark:text-gray-400">
            <span><span className="tnum">{stats.count}</span> lançamentos</span>
            <span>·</span>
            <span>
              Net total ·{' '}
              <span className={`tnum money font-medium ${stats.totalNet >= 0 ? 'text-emerald-500 dark:text-emerald-400' : 'text-red-500 dark:text-red-400'}`}>
                {fmtBRL(stats.totalNet, { sign: true, compact: true })}
              </span>
            </span>
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
        ) : sorted.length === 0 ? (
          <Card>
            <div className="text-sm text-gray-400 dark:text-gray-600 text-center py-12">Nenhum lançamento encontrado.</div>
          </Card>
        ) : (
          <Card padding="p-3">
            <div className="overflow-x-auto -mx-1">
              <table className="w-full text-[12px]">
                <thead>
                  <tr className="text-[10px] uppercase tracking-wider text-gray-500">
                    <th className="text-left font-medium px-2 py-2">Data</th>
                    <th className="text-left font-medium px-2 py-2">Tipo</th>
                    <th className="text-left font-medium px-2 py-2">Ativo</th>
                    <th className="text-right font-medium px-2 py-2">Qtd</th>
                    <th className="text-right font-medium px-2 py-2">Preço unit.</th>
                    <th className="text-right font-medium px-2 py-2">Net</th>
                    <th className="text-right font-medium px-2 py-2" title="PTAX USD/BRL do dia do evento — usado para visualização dolarizada">PTAX</th>
                  </tr>
                </thead>
                <tbody>
                  {grouped.map((g, gi) => (
                    <Fragment key={g.ym}>
                      <tr>
                        <td colSpan={8} className="p-0">
                          <MonthHeader ym={g.ym} first={gi === 0} />
                        </td>
                      </tr>
                      {g.items.map(l => (
                        <Row
                          key={l.id}
                          lan={l}
                          asset={assetById.get(l.asset_id) ?? null}
                          onClick={() => setSelected(l)}
                        />
                      ))}
                    </Fragment>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        )}
      </div>

      {selected && (
        <LancamentoDetailPanel
          key={selected.id}
          lancamento={selected}
          asset={assetById.get(selected.asset_id) ?? null}
          fi={
            (() => {
              const a = assetById.get(selected.asset_id)
              return a ? fiById.get(a.financial_institution_id) ?? null : null
            })()
          }
          onClose={() => setSelected(null)}
          onEdit={() => { void openEdit(selected) }}
          onDeactivate={() => setConfirmDeactivate(selected)}
          onCheckImpact={() => void handleCheckImpact(selected)}
        />
      )}

      {reconciliation && (
        <AffectedSnapshotsModal
          assetId={reconciliation.assetId}
          assetLabel={reconciliation.assetLabel}
          affected={reconciliation.affected}
          triggerEventType={reconciliation.triggerEventType}
          triggerEventId={reconciliation.triggerEventId}
          onClose={() => setReconciliation(null)}
          onApplied={() => setReconciliation(null)}
          onSkipped={() => setReconciliation(null)}
        />
      )}

      {modalOpen && (
        <MovementComposer
          initial={editing}
          assets={assets}
          onSave={handleSave}
          onOptionLifecycleSaved={async () => {
            // Refresh both assets (some lifecycle ops mark the option
            // inactive) and movements (server creates the rows for us).
            try {
              const [a, m] = await Promise.all([
                api.listAssets({ include_inactive: false }),
                api.listAssetMovements({ include_inactive: false, page_size: 200 }),
              ])
              setAssets(a)
              setItems(m.items)
            } catch { /* fail-soft */ }
          }}
          onClose={() => { setModalOpen(false); setEditing(undefined); setEditingAttachments([]) }}
          persistedAttachments={editing ? editingAttachments : undefined}
          onUploadDrafts={handleUploadDrafts}
          onRemovePersistedAttachment={handleRemovePersistedAttachment}
        />
      )}

      {optionModalOpen && (
        <OptionModal
          candidates={assets}
          onClose={() => setOptionModalOpen(false)}
          onSaved={() => {
            // Refresh assets list so the new OPTION appears in the picker,
            // and refresh movements so the SELL_OPEN/BUY_TO_OPEN shows up.
            api.listAssets({ include_inactive: false }).then(setAssets).catch(() => {})
            api.listAssetMovements({ include_inactive: false, page_size: 200 })
              .then(r => setItems(r.items))
              .catch(() => {})
          }}
        />
      )}

      {confirmDeactivate && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/40">
          <div className="w-full max-w-sm bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-700 shadow-xl p-6">
            <h2 className="text-base font-semibold text-gray-900 dark:text-white mb-2">Apagar lançamento?</h2>
            <p className="text-sm text-gray-500 dark:text-gray-400 mb-2">
              <strong>{confirmDeactivate.type_label}</strong> de{' '}
              <strong>{confirmDeactivate.asset_name}</strong> será apagado.
            </p>
            <p className="text-[11px] text-gray-400 dark:text-gray-500 mb-6">
              Fica oculto da lista mas pode ser restaurado depois ativando "Incluir inativos".
            </p>
            <div className="flex justify-end gap-3">
              <button onClick={() => setConfirmDeactivate(null)} className="px-4 py-2 rounded-lg text-sm text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors">
                Cancelar
              </button>
              <button onClick={() => handleDeactivate(confirmDeactivate)} className="px-4 py-2 rounded-lg bg-red-600 hover:bg-red-700 text-white text-sm font-medium transition-colors">
                Apagar
              </button>
            </div>
          </div>
        </div>
      )}
    </AppLayout>
  )
}

function MonthHeader({ ym, first }: { ym: string; first?: boolean }) {
  const [y, m] = ym.split('-')
  const label = `${MONTH_NAMES[parseInt(m, 10) - 1]} · ${y}`
  return (
    <div
      className={`px-2 py-2 ${first ? '' : 'mt-3'} text-[10px] uppercase tracking-wider font-semibold text-gray-500 sticky top-0 bg-gray-50 dark:bg-gray-950 z-[1] border-b border-gray-200 dark:border-gray-800`}
    >
      {label}
    </div>
  )
}

function Row({
  lan: l, asset, onClick,
}: {
  lan: AssetMovementOut
  asset: AssetOut | null
  onClick: () => void
}) {
  const klass = asset ? collapsedOf(asset.asset_class) : null
  const klassColor = klass ? KLASS[klass].color : '#94a3b8'
  const inactive = !l.is_active
  const netTone =
    l.net_amount > 0 ? 'text-emerald-500 dark:text-emerald-400'
    : l.net_amount < 0 ? 'text-red-500 dark:text-red-400'
    : 'text-gray-500 dark:text-gray-400'

  return (
    <tr
      onClick={onClick}
      className={`border-t border-gray-100 dark:border-gray-800 hover:bg-gray-50 dark:hover:bg-gray-800/30 transition-colors cursor-pointer ${
        inactive ? 'opacity-60' : ''
      }`}
    >
      <td className="px-2 py-2 tnum text-gray-400">{fmtDate(l.event_date)}</td>
      <td className="px-2"><TypeBadge code={l.type} label={l.type_label} /></td>
      <td className="px-2">
        <div className="flex items-center gap-2">
          <span className="w-1 h-5 rounded-full" style={{ background: klassColor }} />
          <div className="min-w-0">
            <div className={`font-mono font-medium text-gray-900 dark:text-white ${inactive ? 'line-through' : ''}`}>
              {asset?.ticker || asset?.name || '—'}
            </div>
            {asset?.ticker && asset?.name && (
              <div className="text-[11px] text-gray-500 truncate max-w-[200px]">{asset.name}</div>
            )}
          </div>
        </div>
      </td>
      <td className="px-2 text-right tnum">{fmtNum(l.quantity)}</td>
      <td className="px-2 text-right tnum money text-gray-400">
        {l.unit_price != null ? fmtMoney(l.unit_price, l.currency) : '—'}
      </td>
      <td className="px-2 text-right">
        <div className={`tnum money font-medium ${netTone}`}>{fmtMoney(l.net_amount, l.currency, { sign: true })}</div>
      </td>
      <td className="px-2 text-right tnum text-[11px] text-gray-500" title="PTAX USD/BRL na data do evento">
        {l.fx_rate && Number(l.fx_rate) !== 1
          ? `R$ ${Number(l.fx_rate).toFixed(4)}`
          : '—'}
      </td>
    </tr>
  )
}
