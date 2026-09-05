/* Full asset detail page — mirrors prototypes/index.html `AtivoDetailPage`
 * (line 3274). Same structure, classes, spacing and helpers. */
import { useEffect, useMemo, useState } from 'react'
import { useLocation, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { ArrowLeft, Coins, Edit2, Plus, RefreshCw } from 'lucide-react'
import {
  api,
  type AccountOut,
  type AffectedSnapshotOut,
  type AssetMovementOut,
  type AssetMovementRequest,
  type AssetOut,
  type AssetPerformanceOut,
  type AssetPriceHistoryOut,
  type AssetPriceHistoryPeriod,
  type AssetRequest,
  type AssetSnapshotHistoryOut,
  type AttachmentOut,
  type DistributionOut,
  type DistributionRequest,
  type FinancialInstitutionOut,
  type SyntheticPremiumOut,
  type PositionOut,
  type UserOut,
} from '../lib/api'
import { fmtNum, fmtPct } from '../lib/format'
import { fmtBRL, fmtMoney } from '../lib/money'
import { SOURCE_LABEL, TIER_COLOR, formatRelative } from '../lib/price'
import { useEscapeKey } from '../lib/useEscapeKey'

const PRICE_TIER_TITLE: Record<import('../lib/api').PriceTier, string> = {
  FRESH: 'Atualizado nas últimas 24h',
  STALE: 'Atualizado há mais de 24h',
  OLD: 'Atualizado há mais de 7 dias',
  UNKNOWN: 'Nunca atualizado',
}
import AffectedSnapshotsModal from '../components/AffectedSnapshotsModal'
import AppLayout from '../components/AppLayout'
import AssetModal from '../components/AssetModal'
import DistributionComposer from '../components/DistributionComposer'
import DistributionDetailPanel from '../components/DistributionDetailPanel'
import KpiTile from '../components/KpiTile'
import LancamentoDetailPanel from '../components/LancamentoDetailPanel'
import ManualPriceModal from '../components/ManualPriceModal'
import MovementComposer from '../components/MovementComposer'
import { type AttachmentDraft, type PersistedAttachment } from '../components/NotesAttachmentsField'
import OptionModal from '../components/OptionModal'
import { Card, CcyPill, ClassBadge, FILogo } from '../components/ui'
import AssetDistributionsTab from '../components/asset/AssetDistributionsTab'
import AssetDocsTab from '../components/asset/AssetDocsTab'
import AssetMovementsTab from '../components/asset/AssetMovementsTab'
import AssetOverviewTab from '../components/asset/AssetOverviewTab'
import AssetPerformanceTab from '../components/asset/AssetPerformanceTab'
import AssetTabs, { type AssetTabDef } from '../components/asset/AssetTabs'
import CountryFlag from '../components/asset/CountryFlag'
import { KLASS, collapsedOf } from '../lib/tokens'

// ── Formatters: lib/money.ts + lib/format.ts (spec 81) ──────────────────────

// Spec 81 — abas (ids em EN na URL, labels em PT)
const TAB_IDS = ['overview', 'performance', 'movements', 'distributions', 'docs'] as const
type TabId = typeof TAB_IDS[number]
function parseTab(raw: string | null): TabId {
  return (TAB_IDS as readonly string[]).includes(raw ?? '') ? (raw as TabId) : 'overview'
}

// ── Page ─────────────────────────────────────────────────────────────────────

export default function AssetDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const location = useLocation() as { state?: { from?: string; fromLabel?: string } }
  const backHref = location.state?.from ?? '/assets'
  const backLabel = location.state?.fromLabel
    ? `Voltar pra ${location.state.fromLabel}`
    : 'Voltar pra Ativos'
  const [searchParams, setSearchParams] = useSearchParams()
  const tab = parseTab(searchParams.get('tab'))
  function setTab(next: TabId) {
    if (next === tab) return
    const sp = new URLSearchParams(searchParams)
    if (next === 'overview') sp.delete('tab'); else sp.set('tab', next)
    setSearchParams(sp)   // sem replace: back button volta de aba
  }
  const [me, setMe] = useState<UserOut | null>(null)
  const [asset, setAsset] = useState<AssetOut | null>(null)
  const [fi, setFi] = useState<FinancialInstitutionOut | null>(null)
  const [account, setAccount] = useState<AccountOut | null>(null)
  const [position, setPosition] = useState<PositionOut | null>(null)
  const [movements, setMovements] = useState<AssetMovementOut[]>([])
  const [distributions, setDistributions] = useState<DistributionOut[]>([])
  const [syntheticPremiums, setSyntheticPremiums] = useState<SyntheticPremiumOut[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [optionModalOpen, setOptionModalOpen] = useState(false)
  const [optionsRefresh, setOptionsRefresh] = useState(0)
  const [underlying, setUnderlying] = useState<AssetOut | null>(null)
  const [refreshingPrice, setRefreshingPrice] = useState(false)
  const [priceMsg, setPriceMsg] = useState<{ kind: 'ok' | 'err'; text: string } | null>(null)
  const [manualPriceOpen, setManualPriceOpen] = useState(false)
  const [editAssetOpen, setEditAssetOpen] = useState(false)
  const [institutions, setInstitutions] = useState<FinancialInstitutionOut[]>([])
  // Spec 46 — real price history derived from snapshots.
  const [pricePeriod, setPricePeriod] = useState<AssetPriceHistoryPeriod>('24m')
  const [priceHistory, setPriceHistory] = useState<AssetPriceHistoryOut | null>(null)
  // Spec 50 — snapshot history table + chart.
  const [snapshotHistory, setSnapshotHistory] = useState<AssetSnapshotHistoryOut | null>(null)
  const [snapshotHistoryLoading, setSnapshotHistoryLoading] = useState(false)
  // Spec 81 — rentabilidade mês a mês (carrega quando a aba abre).
  const [performance, setPerformance] = useState<AssetPerformanceOut | null>(null)
  const [performanceLoading, setPerformanceLoading] = useState(false)
  const [performanceError, setPerformanceError] = useState<string | null>(null)
  // Spec 81 — Documentos & dados: anexos do ativo (lazy) + auto-edit vindo do header.
  const [assetAttachments, setAssetAttachments] = useState<AttachmentOut[] | null>(null)
  const [docsAutoEdit, setDocsAutoEdit] = useState(false)
  const [confirmDeactivateAsset, setConfirmDeactivateAsset] = useState(false)

  // Lançamentos sub-flow: side panel + composer + deactivate + spec 51 reconciliation
  const [selectedMovement, setSelectedMovement] = useState<AssetMovementOut | null>(null)
  const [editingMovement, setEditingMovement] = useState<AssetMovementOut | undefined>(undefined)
  const [movementComposerOpen, setMovementComposerOpen] = useState(false)
  const [editingAttachments, setEditingAttachments] = useState<PersistedAttachment[]>([])
  const [confirmDeactivate, setConfirmDeactivate] = useState<AssetMovementOut | null>(null)
  const [lastClosedPeriodEnd, setLastClosedPeriodEnd] = useState<string | null>(null)
  const [reconciliation, setReconciliation] = useState<{
    affected: AffectedSnapshotOut[]
    assetId: string
    assetLabel: string
    triggerEventId: string
    triggerEventType: string
  } | null>(null)
  // Proventos sub-flow (spec 81): painel + composer + deactivate.
  const [selectedDistribution, setSelectedDistribution] = useState<DistributionOut | null>(null)
  const [editingDistribution, setEditingDistribution] = useState<DistributionOut | undefined>(undefined)
  const [distributionComposerOpen, setDistributionComposerOpen] = useState(false)
  const [editingDistAttachments, setEditingDistAttachments] = useState<PersistedAttachment[]>([])
  const [confirmDeactivateDist, setConfirmDeactivateDist] = useState<DistributionOut | null>(null)
  // Sub-modals já tratam ESC. O hook só fecha os inline confirms.
  useEscapeKey(() => {
    if (confirmDeactivate) setConfirmDeactivate(null)
    if (confirmDeactivateDist) setConfirmDeactivateDist(null)
    if (confirmDeactivateAsset) setConfirmDeactivateAsset(false)
  })

  function showMsg(kind: 'ok' | 'err', text: string) {
    setPriceMsg({ kind, text })
    window.setTimeout(() => setPriceMsg(null), 4000)
  }

  async function refreshAssetAttachments() {
    if (!asset) return
    try {
      setAssetAttachments(await api.listAttachments('asset', asset.id))
    } catch { /* fail-soft */ }
  }

  async function handleNotesSave(notes: string) {
    if (!asset) return
    const updated = await api.patchAsset(asset.id, { notes: notes.trim() ? notes : null })
    setAsset(updated)
  }

  function handleAssetSaved(updated: AssetOut) {
    const fiChanged = updated.account_id !== asset?.account_id
    setAsset(updated)
    showMsg('ok', 'Dados do ativo salvos.')
    if (fiChanged) {
      api.getAccount(updated.account_id)
        .then(acc => {
          setAccount(acc)
          setFi(institutions.find(f => f.id === acc.financial_institution_id) ?? null)
        })
        .catch(() => { /* fail-soft */ })
    }
  }

  async function handleAssetDeactivate() {
    if (!asset) return
    try {
      const updated = await api.deactivateAsset(asset.id)
      setAsset(updated)
      showMsg('ok', 'Ativo zerado.')
    } catch (e) {
      showMsg('err', e instanceof Error ? e.message : 'Erro ao zerar o ativo')
    } finally {
      setConfirmDeactivateAsset(false)
    }
  }

  function openNewDistribution() {
    setEditingDistribution(undefined)
    setEditingDistAttachments([])
    setDistributionComposerOpen(true)
  }

  const sortByDateDesc = <T extends { event_date: string }>(xs: T[]) =>
    [...xs].sort((a, b) => b.event_date.localeCompare(a.event_date))

  async function handleDistributionSave(data: DistributionRequest) {
    if (editingDistribution) {
      const updated = await api.updateDistribution(editingDistribution.id, data)
      setDistributions(prev => sortByDateDesc(prev.map(d => d.id === updated.id ? updated : d)))
      if (selectedDistribution?.id === updated.id) setSelectedDistribution(updated)
      return updated
    }
    const created = await api.createDistribution(data)
    setDistributions(prev => sortByDateDesc([created, ...prev]))
    return created
  }

  async function handleDistributionUploadDrafts(entityId: string, drafts: AttachmentDraft[]) {
    const results = await Promise.allSettled(
      drafts.map(d => api.uploadAttachment('distribution', entityId, d.file)),
    )
    const failed = results
      .map((r, i) => ({ r, name: drafts[i].name }))
      .filter(x => x.r.status === 'rejected')
    if (failed.length) {
      throw new Error(failed
        .map(x => `${x.name}: ${(x.r as PromiseRejectedResult).reason?.message ?? 'erro desconhecido'}`)
        .join(' · '))
    }
  }

  async function reloadDistAttachments(distId: string) {
    try {
      const list = await api.listAttachments('distribution', distId)
      setEditingDistAttachments(list.map(a => ({
        id: a.id, filename: a.filename, size_bytes: a.size_bytes,
        mime_type: a.mime_type, kind: a.kind,
      })))
    } catch {
      setEditingDistAttachments([])
    }
  }

  async function handleDistributionRemoveAttachment(attachmentId: string) {
    await api.deleteAttachment(attachmentId)
    if (editingDistribution) await reloadDistAttachments(editingDistribution.id)
  }

  async function openDistributionEdit(d: DistributionOut) {
    setEditingDistribution(d)
    setDistributionComposerOpen(true)
    await reloadDistAttachments(d.id)
  }

  async function handleDistributionDeactivate(d: DistributionOut) {
    await api.deactivateDistribution(d.id)
    setDistributions(prev => prev.filter(x => x.id !== d.id))
    if (selectedDistribution?.id === d.id) setSelectedDistribution(null)
    setConfirmDeactivateDist(null)
  }

  async function handleRefreshPrice() {
    if (!asset || refreshingPrice) return
    setRefreshingPrice(true)
    setPriceMsg(null)
    try {
      const r = await api.refreshAssetPrice(asset.id)
      if (r.status === 'ok') {
        setPriceMsg({ kind: 'ok', text: `Atualizado: ${r.ticker ?? asset.ticker} = ${r.new_price}` })
        const updated = await api.getAsset(asset.id)
        setAsset(updated)
      } else {
        setPriceMsg({ kind: 'err', text: r.error ?? `${r.status}` })
      }
    } catch (e) {
      setPriceMsg({ kind: 'err', text: e instanceof Error ? e.message : 'Erro' })
    } finally {
      setRefreshingPrice(false)
      window.setTimeout(() => setPriceMsg(null), 4000)
    }
  }

  function handleEditPrice() {
    setManualPriceOpen(true)
  }

  async function refreshMovementsAndPosition() {
    if (!asset) return
    try {
      const [pos, movs] = await Promise.all([
        api.getAssetPosition(asset.id).catch(() => null),
        api.listAssetMovementsForAsset(asset.id, { page: 1, page_size: 200, include_inactive: false })
          .then(p => p.items).catch(() => [] as AssetMovementOut[]),
      ])
      if (pos) setPosition(pos)
      setMovements([...movs].sort((a, b) => b.event_date.localeCompare(a.event_date)))
    } catch { /* fail-soft */ }
  }

  async function handleMovementSave(data: AssetMovementRequest) {
    let saved: AssetMovementOut
    const isUpdate = !!editingMovement
    if (editingMovement) {
      saved = await api.updateAssetMovement(editingMovement.id, data)
      setMovements(prev => prev.map(l => l.id === saved.id ? saved : l))
      if (selectedMovement?.id === saved.id) setSelectedMovement(saved)
    } else {
      saved = await api.createAssetMovement(data)
      setMovements(prev => [saved, ...prev].sort((a, b) => b.event_date.localeCompare(a.event_date)))
    }
    void refreshMovementsAndPosition()
    // Spec 51 — sonda fechamentos afetados; abre o AffectedSnapshotsModal se houver.
    try {
      const affected = await api.previewAffectedSnapshots(saved.asset_id, saved.event_date)
      if (affected.length > 0) {
        setReconciliation({
          affected,
          assetId: saved.asset_id,
          assetLabel: saved.asset_ticker || saved.asset_name,
          triggerEventId: saved.id,
          triggerEventType: isUpdate ? 'asset_movement.update' : 'asset_movement.create',
        })
      }
    } catch (e) {
      console.error('Failed to preview affected snapshots', e)
    }
    return saved
  }

  async function handleMovementCheckImpact(mov: AssetMovementOut) {
    try {
      const affected = await api.previewAffectedSnapshots(mov.asset_id, mov.event_date)
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

  async function handleMovementUploadDrafts(entityId: string, drafts: AttachmentDraft[]) {
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

  async function handleMovementRemoveAttachment(attachmentId: string) {
    await api.deleteAttachment(attachmentId)
    if (editingMovement) {
      const list = await api.listAttachments('movement', editingMovement.id)
      setEditingAttachments(list.map(a => ({
        id: a.id, filename: a.filename, size_bytes: a.size_bytes,
        mime_type: a.mime_type, kind: a.kind,
      })))
    }
  }

  async function openMovementEdit(l: AssetMovementOut) {
    setEditingMovement(l)
    setMovementComposerOpen(true)
    try {
      const list = await api.listAttachments('movement', l.id)
      setEditingAttachments(list.map(a => ({
        id: a.id, filename: a.filename, size_bytes: a.size_bytes,
        mime_type: a.mime_type, kind: a.kind,
      })))
    } catch {
      setEditingAttachments([])
    }
  }

  async function handleMovementDeactivate(l: AssetMovementOut) {
    await api.deactivateAssetMovement(l.id)
    setMovements(prev => prev.filter(x => x.id !== l.id))
    if (selectedMovement?.id === l.id) setSelectedMovement(null)
    setConfirmDeactivate(null)
    void refreshMovementsAndPosition()
  }

  async function handleSaveAsset(data: AssetRequest) {
    if (!asset) return
    const updated = await api.updateAsset(asset.id, data)
    setAsset(updated)
    if (updated.account_id !== asset.account_id) {
      const acc = await api.getAccount(updated.account_id).catch(() => null)
      if (acc) {
        setAccount(acc)
        setFi(institutions.find(f => f.id === acc.financial_institution_id) ?? null)
      }
    }
  }

  useEffect(() => {
    api.me().then(setMe).catch(() => navigate('/login'))
  }, [navigate])

  // Carrega o último period_end_date CLOSED — gate do "Verificar impacto".
  useEffect(() => {
    if (!me) return
    api.listSnapshots()
      .then(list => {
        const closed = list
          .filter(s => s.status === 'CLOSED')
          .map(s => s.period_end_date)
          .sort()
        setLastClosedPeriodEnd(closed.length > 0 ? closed[closed.length - 1] : null)
      })
      .catch(() => { /* silent */ })
  }, [me])

  useEffect(() => {
    if (!me || !id) return
    setLoading(true)
    setError('')
    api.getAsset(id)
      .then(async a => {
        setAsset(a)
        const fis = await api.listFinancialInstitutions().catch(() => [])
        setInstitutions(fis)
        const acc = await api.getAccount(a.account_id).catch(() => null)
        if (acc) {
          setAccount(acc)
          setFi(fis.find(f => f.id === acc.financial_institution_id) ?? null)
        }
        // For OPTION assets, also load the underlying for OptionContextCard.
        if (a.asset_class === 'OPTION' && a.underlying_id) {
          const u = await api.getAsset(a.underlying_id).catch(() => null)
          setUnderlying(u)
        } else {
          setUnderlying(null)
        }
      })
      .then(() => Promise.all([
        api.getAssetPosition(id).catch(() => null),
        api.listAssetMovementsForAsset(id, { page: 1, page_size: 200, include_inactive: false })
          .then(p => p.items).catch(() => [] as AssetMovementOut[]),
        api.listDistributionsForAsset(id, {
          page: 1, page_size: 200, include_inactive: false, include_synthetic: true,
        }).catch(() => ({ items: [] as DistributionOut[], synthetic_premiums: [] as SyntheticPremiumOut[] })),
      ]))
      .then(([pos, movs, distPage]) => {
        setPosition(pos)
        setMovements([...movs].sort((a, b) => b.event_date.localeCompare(a.event_date)))
        setDistributions([...distPage.items].sort((a, b) => b.event_date.localeCompare(a.event_date)))
        setSyntheticPremiums(distPage.synthetic_premiums ?? [])
      })
      .catch(e => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false))
  }, [me, id])

  const distSumBRL = useMemo(
    () => distributions.reduce((s, d) => {
      const fx = d.fx_rate || 1
      const brl = d.currency === 'BRL' ? d.net_amount : d.net_amount * fx
      return s + brl
    }, 0),
    [distributions],
  )
  // Spec 46 — real price history fetched per (asset, period). Spec 81: só na
  // aba Visão geral (é a aba padrão; as outras não usam).
  useEffect(() => {
    if (!me || !id || tab !== 'overview') return
    let cancelled = false
    api.getAssetPriceHistory(id, pricePeriod)
      .then(h => { if (!cancelled) setPriceHistory(h) })
      .catch(() => { if (!cancelled) setPriceHistory(null) })
    return () => { cancelled = true }
  }, [me, id, pricePeriod, tab])

  // Spec 50 — snapshot history (tabela de fechamentos + sparkline). Spec 81:
  // carrega quando a aba Fechamentos abre; cacheado no shell depois disso.
  useEffect(() => {
    if (!me || !id || tab !== 'performance' || snapshotHistory) return
    let cancelled = false
    setSnapshotHistoryLoading(true)
    api.getAssetSnapshotHistory(id)
      .then(h => { if (!cancelled) setSnapshotHistory(h) })
      .catch(() => { if (!cancelled) setSnapshotHistory(null) })
      .finally(() => { if (!cancelled) setSnapshotHistoryLoading(false) })
    return () => { cancelled = true }
  }, [me, id, tab, snapshotHistory])

  // Spec 81 — anexos do ativo, lazy na aba Documentos.
  useEffect(() => {
    if (!me || !id || tab !== 'docs' || assetAttachments) return
    let cancelled = false
    api.listAttachments('asset', id)
      .then(list => { if (!cancelled) setAssetAttachments(list) })
      .catch(() => { if (!cancelled) setAssetAttachments([]) })
    return () => { cancelled = true }
  }, [me, id, tab, assetAttachments])

  // Spec 81 — performance (retorno total mês a mês), lazy por aba. Fechamentos
  // são congelados, então o cache no shell não fica stale com lançamentos novos.
  useEffect(() => {
    if (!me || !id || tab !== 'performance' || performance) return
    let cancelled = false
    setPerformanceLoading(true)
    setPerformanceError(null)
    api.getAssetPerformance(id)
      .then(p => { if (!cancelled) setPerformance(p) })
      .catch(e => { if (!cancelled) setPerformanceError(e instanceof Error ? e.message : 'Erro') })
      .finally(() => { if (!cancelled) setPerformanceLoading(false) })
    return () => { cancelled = true }
  }, [me, id, tab, performance])

  if (!me) return null

  if (loading) {
    return (
      <AppLayout user={me}>
        <div className="text-sm text-gray-400 py-16 text-center">Carregando…</div>
      </AppLayout>
    )
  }
  if (error || !asset) {
    return (
      <AppLayout user={me}>
        <Card>
          <div className="text-sm text-red-500 py-6 text-center">{error || 'Ativo não encontrado.'}</div>
        </Card>
      </AppLayout>
    )
  }

  const klass = collapsedOf(asset.asset_class)
  const klassColor = KLASS[klass].color
  const ccy = asset.currency

  // Derived values
  const qty = Number(position?.quantity_held ?? 0)
  const avg = position?.average_cost != null ? Number(position.average_cost) : null
  const price = (position?.current_price ?? asset.current_price) != null
    ? Number(position?.current_price ?? asset.current_price)
    : null
  // Fase 3.2 (2026-07-22): current_value vem da API (backend aplica
  // effective_qty=1 pra value-mode). Antes calculávamos client-side
  // price × qty, o que inflava N× pra FUND/PREV/FGTS/RE onde qty=N
  // aportes. Fallback pra price × qty só quando a API não devolve
  // (asset sem posição no fluxo antigo).
  // Spec 78 — o fallback price × qty só faz sentido em modo cotado: em modo
  // valor qty não é posição (era o nº de lançamentos) e hoje vem 0.
  const value = position?.current_value != null
    ? Number(position.current_value)
    : (!position?.is_value_mode && price != null && qty ? price * qty : null)
  // `cost` fica em NATIVE currency pra bater com `value` no P&L. Em
  // modo cotado, avg × qty já é o correto. Em value-mode, position
  // devolve rentabilidade% pronta (o backend soma non_cotado_basis_brl
  // corretamente); o P&L per-asset em native não é 100% preciso mas o
  // KPI relevante em modo valor é rentabilidade, não pl absoluto.
  const cost = avg != null && qty ? avg * qty : null
  const pl = value != null && cost != null ? value - cost : null
  const valueBRL = position?.current_value_brl != null ? Number(position.current_value_brl) : null
  const costBRL = position?.total_invested_brl != null ? Number(position.total_invested_brl) : null
  // Spec 81 — sem PTAX hardcoded: o câmbio implícito vem da própria posição
  // (current_value_brl / current_value), e o P&L em BRL do investido em BRL.
  const impliedFx = value != null && value > 0 && valueBRL != null ? valueBRL / value : null
  const plBRL = valueBRL != null && costBRL != null ? valueBRL - costBRL : null
  const variation = position?.variation != null ? Number(position.variation) : null
  const rentabilidade = position?.rentabilidade != null ? Number(position.rentabilidade) : null
  const yoc = (costBRL && costBRL > 0) ? distSumBRL / costBRL : null
  const dy = (valueBRL && valueBRL > 0) ? distSumBRL / valueBRL : null
  const lastMovementDate = movements[0]?.event_date

  const tabs: AssetTabDef<TabId>[] = [
    { id: 'overview', label: 'Visão geral' },
    { id: 'performance', label: 'Fechamentos & rentabilidade' },
    { id: 'movements', label: 'Lançamentos', count: movements.length },
    { id: 'distributions', label: 'Proventos', count: distributions.length + syntheticPremiums.length },
    { id: 'docs', label: 'Documentos & dados' },
  ]
  function openNewMovement() {
    setEditingMovement(undefined)
    setEditingAttachments([])
    setMovementComposerOpen(true)
  }

  return (
    <AppLayout user={me}>
      <div className="space-y-6">
        <button
          onClick={() => navigate(backHref)}
          className="inline-flex items-center gap-1.5 text-[11px] text-gray-500 hover:text-gray-700 dark:hover:text-gray-300"
        >
          <ArrowLeft className="w-3.5 h-3.5" /> {backLabel}
        </button>

        {/* Header */}
        <Card padding="p-6">
          <div className="flex items-start gap-4">
            <span className="w-1.5 h-14 rounded-full" style={{ background: klassColor }} />
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                <h1 className="text-3xl font-mono font-semibold text-gray-900 dark:text-white">
                  {asset.ticker || asset.name}
                </h1>
                <CountryFlag country={asset.country} />
                <ClassBadge klass={klass} size="xs" withDot={false} />
                <CcyPill ccy={ccy} />
                {!asset.is_active && (
                  <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium uppercase tracking-wider bg-gray-200 dark:bg-gray-800 text-gray-500">
                    Zerado
                  </span>
                )}
              </div>
              <div className="text-sm text-gray-500 mt-1">{asset.name}</div>
              {fi && account && (
                <div className="mt-2 flex items-center gap-2 text-[12px] text-gray-500">
                  <FILogo slug={fi.logo_slug} shortName={fi.short_name} size="sm" />
                  <span className="hover:text-gray-700 dark:hover:text-gray-300">{fi.long_name}</span>
                  <span>·</span>
                  <span className="hover:text-gray-700 dark:hover:text-gray-300">{account.name}</span>
                </div>
              )}
            </div>
            <div className="flex items-center gap-2 shrink-0">
              {/* Atualizar preço — sempre presente; disabled p/ MANUAL */}
              {(() => {
                const isManual = !asset.price_source || asset.price_source === 'MANUAL'
                return (
                  <button
                    onClick={handleRefreshPrice}
                    disabled={isManual || refreshingPrice}
                    title={isManual
                      ? 'Sem fonte automatizada — use "Editar preço" para atualizar manualmente'
                      : `Buscar preço em ${SOURCE_LABEL[asset.price_source!]}`}
                    className={`h-8 px-3 inline-flex items-center gap-1.5 rounded-lg text-[12px] transition-colors ${
                      isManual
                        ? 'bg-gray-50 dark:bg-gray-900/40 text-gray-400 dark:text-gray-600 border border-dashed border-gray-300 dark:border-gray-800 cursor-not-allowed'
                        : 'bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700'
                    }`}
                  >
                    <RefreshCw className={`w-3.5 h-3.5 ${refreshingPrice ? 'animate-spin' : ''}`} />
                    {refreshingPrice ? 'Atualizando…' : 'Atualizar preço'}
                  </button>
                )
              })()}
              {/* Editar preço — sempre disponível (manual edit, stub p/ spec 28) */}
              <button
                onClick={handleEditPrice}
                title="Editar preço atual manualmente"
                className="h-8 px-3 inline-flex items-center gap-1.5 rounded-lg text-[12px] bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700 transition-colors"
              >
                <Edit2 className="w-3.5 h-3.5" /> Editar preço
              </button>
              <button
                onClick={() => { setDocsAutoEdit(true); setTab('docs') }}
                data-testid="header-edit-asset"
                title="Editar dados do ativo (classe, nome, ticker, custodiante…)"
                className="h-8 px-3 inline-flex items-center gap-1.5 rounded-lg text-[12px] bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700 transition-colors"
              >
                <Edit2 className="w-3.5 h-3.5" /> Editar ativo
              </button>
              <button
                onClick={openNewDistribution}
                data-testid="header-new-distribution"
                className="h-8 px-3 inline-flex items-center gap-1.5 rounded-lg text-[12px] bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700 transition-colors"
              >
                <Coins className="w-3.5 h-3.5" /> + Provento
              </button>
              <button
                onClick={openNewMovement}
                data-testid="header-new-movement"
                className="h-8 px-3 inline-flex items-center gap-1.5 rounded-lg text-[12px] bg-indigo-500 hover:bg-indigo-400 text-white transition-colors"
              >
                <Plus className="w-3.5 h-3.5" /> Lançamento
              </button>
              {asset.asset_class !== 'OPTION' && (
                <button
                  onClick={() => setOptionModalOpen(true)}
                  className="h-8 px-3 inline-flex items-center gap-1.5 rounded-lg text-[12px] bg-indigo-500 hover:bg-indigo-400 text-white transition-colors"
                >
                  <Plus className="w-3.5 h-3.5" /> Opção
                </button>
              )}
            </div>
          </div>

          {/* Price-refresh toast (inline, auto-dismiss) */}
          {priceMsg && (
            <div
              className={`mt-3 text-[11px] rounded-md px-3 py-1.5 inline-flex items-center gap-2 ${
                priceMsg.kind === 'ok'
                  ? 'bg-emerald-50 dark:bg-emerald-900/20 text-emerald-700 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-900'
                  : 'bg-amber-50 dark:bg-amber-900/20 text-amber-700 dark:text-amber-300 border border-amber-200 dark:border-amber-900'
              }`}
            >
              {priceMsg.text}
            </div>
          )}

          {/* KPI grid 4×2 */}
          <div className="mt-6 grid grid-cols-2 lg:grid-cols-4 gap-3">
            <KpiTile
              label="Posição"
              value={fmtMoney(value, ccy, { compact: true })}
              sub={ccy === 'USD' && valueBRL != null
                ? fmtBRL(valueBRL, { compact: true })
                : `${fmtNum(qty, qty < 1 ? 4 : 0)} unidades`}
            />
            <KpiTile label="Preço médio" value={fmtMoney(avg, ccy)} />
            <KpiTile
              label="Preço atual"
              value={fmtMoney(price, ccy)}
              cornerDot={{
                color: TIER_COLOR[asset.price_tier],
                title: PRICE_TIER_TITLE[asset.price_tier],
              }}
              sub={
                asset.price_updated_at ? (
                  <>
                    <span data-testid="price-age">{formatRelative(asset.price_updated_at)}</span>
                    {asset.price_source && (
                      <>
                        <span className="mx-1">·</span>
                        <span data-testid="price-source">{SOURCE_LABEL[asset.price_source]}</span>
                      </>
                    )}
                    {ccy === 'USD' && price != null && impliedFx != null && (
                      <>
                        <span className="mx-1">·</span>
                        <span className="tnum" data-testid="price-brl">{fmtBRL(price * impliedFx)}</span>
                      </>
                    )}
                  </>
                ) : (
                  'sem preço atual'
                )
              }
            />
            <KpiTile
              label="P&L"
              value={fmtMoney(pl, ccy, { sign: true, compact: true })}
              sub={ccy === 'USD' && plBRL != null ? fmtBRL(plBRL, { sign: true, compact: true }) : undefined}
              intent={pl == null ? undefined : pl >= 0 ? 'positive' : 'negative'}
            />
            <KpiTile
              label="Variação"
              value={fmtPct(variation, 2, true)}
              sub="apenas preço"
              intent={variation == null ? undefined : variation >= 0 ? 'positive' : 'negative'}
            />
            <KpiTile
              label="Rentabilidade"
              value={fmtPct(rentabilidade, 2, true)}
              sub="preço + proventos"
              intent={rentabilidade == null ? undefined : rentabilidade >= 0 ? 'positive' : 'negative'}
            />
            <KpiTile
              label="YoC"
              value={fmtPct(yoc, 1)}
              sub={fmtBRL(distSumBRL, { compact: true })}
              intent={yoc != null && yoc > 0 ? 'positive' : undefined}
            />
            <KpiTile label="DY" value={fmtPct(dy, 1)} sub="anualizado" />
          </div>
        </Card>

        {/* Spec 81 — abas */}
        <AssetTabs<TabId>
          tabs={tabs}
          value={tab}
          onChange={setTab}
        />

        {tab === 'overview' && (
          <AssetOverviewTab
            asset={asset}
            me={me}
            underlying={underlying}
            position={position}
            priceHistory={priceHistory}
            pricePeriod={pricePeriod}
            onPricePeriodChange={setPricePeriod}
            klassColor={klassColor}
            optionsRefresh={optionsRefresh}
            onOptionsAction={() => setOptionsRefresh(n => n + 1)}
            onAddOption={() => setOptionModalOpen(true)}
          />
        )}

        {tab === 'performance' && (
          <AssetPerformanceTab
            assetId={asset.id}
            snapshotHistory={snapshotHistory}
            snapshotHistoryLoading={snapshotHistoryLoading}
            movements={movements}
            performance={performance}
            performanceLoading={performanceLoading}
            performanceError={performanceError}
          />
        )}

        {tab === 'movements' && (
          <AssetMovementsTab
            movements={movements}
            onRowClick={setSelectedMovement}
            onNew={openNewMovement}
          />
        )}

        {tab === 'distributions' && (
          <AssetDistributionsTab
            distributions={distributions}
            syntheticPremiums={syntheticPremiums}
            onRowClick={setSelectedDistribution}
            onNew={openNewDistribution}
          />
        )}

        {tab === 'docs' && (
          <AssetDocsTab
            asset={asset}
            fi={fi}
            account={account}
            institutions={institutions}
            canDeactivate={me.role !== 'member'}
            costBRL={costBRL}
            receivedBRL={distSumBRL}
            movementsCount={movements.length}
            lastMovementDate={lastMovementDate}
            autoEdit={docsAutoEdit}
            onAutoEditConsumed={() => setDocsAutoEdit(false)}
            onSaved={handleAssetSaved}
            onError={(msg) => showMsg('err', msg)}
            onEditDetails={() => setEditAssetOpen(true)}
            onDeactivate={() => setConfirmDeactivateAsset(true)}
            attachments={assetAttachments ?? []}
            onAttachmentsChanged={refreshAssetAttachments}
            onNotesSave={handleNotesSave}
          />
        )}
      </div>

      {optionModalOpen && (
        <OptionModal
          underlying={asset}
          onClose={() => setOptionModalOpen(false)}
          onSaved={() => setOptionsRefresh(n => n + 1)}
        />
      )}

      {editAssetOpen && institutions.length > 0 && (
        <AssetModal
          initial={asset}
          institutions={institutions}
          onSave={handleSaveAsset}
          onClose={() => setEditAssetOpen(false)}
        />
      )}

      {manualPriceOpen && (
        <ManualPriceModal
          asset={asset}
          onClose={() => setManualPriceOpen(false)}
          onSaved={(result) => {
            setManualPriceOpen(false)
            setAsset((prev) => prev ? ({
              ...prev,
              current_price: result.price,
              price_updated_at: result.price_updated_at,
              price_source: result.price_source,
              price_tier: 'FRESH',
            }) : prev)
            setPriceMsg({ kind: 'ok', text: `Preço atualizado para ${result.price.toLocaleString('pt-BR', { style: 'currency', currency: asset.currency })}` })
            window.setTimeout(() => setPriceMsg(null), 3000)
          }}
        />
      )}

      {selectedMovement && (
        <LancamentoDetailPanel
          key={selectedMovement.id}
          lancamento={selectedMovement}
          asset={asset}
          fi={fi}
          onClose={() => setSelectedMovement(null)}
          onEdit={() => { void openMovementEdit(selectedMovement) }}
          onDeactivate={() => setConfirmDeactivate(selectedMovement)}
          onCheckImpact={() => void handleMovementCheckImpact(selectedMovement)}
          lastClosedPeriodEnd={lastClosedPeriodEnd}
        />
      )}

      {movementComposerOpen && (
        <MovementComposer
          initial={editingMovement}
          preselectedAsset={asset}
          assets={[asset]}
          onSave={handleMovementSave}
          onOptionLifecycleSaved={async () => { void refreshMovementsAndPosition() }}
          onClose={() => {
            setMovementComposerOpen(false)
            setEditingMovement(undefined)
            setEditingAttachments([])
          }}
          persistedAttachments={editingMovement ? editingAttachments : undefined}
          onUploadDrafts={handleMovementUploadDrafts}
          onRemovePersistedAttachment={handleMovementRemoveAttachment}
        />
      )}

      {selectedDistribution && (
        <DistributionDetailPanel
          key={selectedDistribution.id}
          distribution={selectedDistribution}
          asset={asset}
          fi={fi}
          onClose={() => setSelectedDistribution(null)}
          onEdit={() => { void openDistributionEdit(selectedDistribution) }}
          onDeactivate={() => setConfirmDeactivateDist(selectedDistribution)}
          onUpdated={(d) => {
            setDistributions(prev => prev.map(x => x.id === d.id ? d : x))
            setSelectedDistribution(d)
          }}
        />
      )}

      {distributionComposerOpen && (
        <DistributionComposer
          initial={editingDistribution}
          preselectedAsset={asset}
          institutions={institutions}
          assets={[asset]}
          onSave={handleDistributionSave}
          onClose={() => {
            setDistributionComposerOpen(false)
            setEditingDistribution(undefined)
            setEditingDistAttachments([])
          }}
          persistedAttachments={editingDistribution ? editingDistAttachments : undefined}
          onUploadDrafts={handleDistributionUploadDrafts}
          onRemovePersistedAttachment={handleDistributionRemoveAttachment}
        />
      )}

      {confirmDeactivateDist && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/40">
          <div className="w-full max-w-sm bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-700 shadow-xl p-6">
            <h2 className="text-base font-semibold text-gray-900 dark:text-white mb-2">Apagar provento?</h2>
            <p className="text-sm text-gray-500 dark:text-gray-400 mb-2">
              <strong>{confirmDeactivateDist.type_label}</strong> de{' '}
              <strong>{asset.ticker || asset.name}</strong> será apagado.
            </p>
            <p className="text-[11px] text-gray-400 dark:text-gray-500 mb-6">
              Fica oculto da lista mas pode ser restaurado depois ativando "Incluir inativos".
            </p>
            <div className="flex justify-end gap-3">
              <button onClick={() => setConfirmDeactivateDist(null)} className="px-4 py-2 rounded-lg text-sm text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors">Cancelar</button>
              <button onClick={() => handleDistributionDeactivate(confirmDeactivateDist)} className="px-4 py-2 rounded-lg bg-red-600 hover:bg-red-700 text-white text-sm font-medium transition-colors">Apagar</button>
            </div>
          </div>
        </div>
      )}

      {confirmDeactivateAsset && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/40">
          <div className="w-full max-w-sm bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-700 shadow-xl p-6">
            <h2 className="text-base font-semibold text-gray-900 dark:text-white mb-2">Zerar ativo?</h2>
            <p className="text-sm text-gray-500 dark:text-gray-400 mb-2">
              <strong>{asset.ticker || asset.name}</strong> sai das listas e dos próximos fechamentos.
            </p>
            <p className="text-[11px] text-gray-400 dark:text-gray-500 mb-6">
              Lançamentos, proventos e histórico de fechamentos ficam preservados.
            </p>
            <div className="flex justify-end gap-3">
              <button onClick={() => setConfirmDeactivateAsset(false)} className="px-4 py-2 rounded-lg text-sm text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors">Cancelar</button>
              <button onClick={() => void handleAssetDeactivate()} data-testid="confirm-deactivate-asset" className="px-4 py-2 rounded-lg bg-red-600 hover:bg-red-700 text-white text-sm font-medium transition-colors">Zerar</button>
            </div>
          </div>
        </div>
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
              <button onClick={() => setConfirmDeactivate(null)} className="px-4 py-2 rounded-lg text-sm text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors">Cancelar</button>
              <button onClick={() => handleMovementDeactivate(confirmDeactivate)} className="px-4 py-2 rounded-lg bg-red-600 hover:bg-red-700 text-white text-sm font-medium transition-colors">Apagar</button>
            </div>
          </div>
        </div>
      )}
    </AppLayout>
  )
}
