/* Full asset detail page — mirrors prototypes/index.html `AtivoDetailPage`
 * (line 3274). Same structure, classes, spacing and helpers. */
import { useEffect, useMemo, useState } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { ArrowLeft, Coins, Edit2, MoreHorizontal, Plus, RefreshCw } from 'lucide-react'
import {
  api,
  type AccountOut,
  type AffectedSnapshotOut,
  type AssetMovementOut,
  type AssetMovementRequest,
  type AssetOut,
  type AssetPriceHistoryOut,
  type AssetPriceHistoryPeriod,
  type AssetRequest,
  type AssetSnapshotHistoryOut,
  type DistributionOut,
  type FinancialInstitutionOut,
  type PositionOut,
  type UserOut,
} from '../lib/api'
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
import AssetDistributionsChart from '../components/AssetDistributionsChart'
import AssetModal from '../components/AssetModal'
import AssetSnapshotsCard from '../components/AssetSnapshotsCard'
import ValuationCard from '../components/ValuationCard'
import LancamentoDetailPanel from '../components/LancamentoDetailPanel'
import ManualPriceModal from '../components/ManualPriceModal'
import MovementComposer from '../components/MovementComposer'
import { type AttachmentDraft, type PersistedAttachment } from '../components/NotesAttachmentsField'
import OpenOptionsCard from '../components/OpenOptionsCard'
import OptionContextCard from '../components/OptionContextCard'
import OptionModal from '../components/OptionModal'
import Sparkline from '../components/Sparkline'
import {
  Card, CcyPill, ClassBadge, FILogo, GroupingToggle, SectionTitle,
} from '../components/ui'
import { KLASS, collapsedOf } from '../lib/tokens'

// ── Formatters (match prototype) ─────────────────────────────────────────────

// Compact suffix system-wide: "k" e "M" (lib/money.ts). pt-BR usa "mil"/"mi"
// no Intl.NumberFormat com notation:'compact' — proibido.
function compactSuffix(abs: number): { value: string; suffix: string } | null {
  if (abs >= 1_000_000) {
    return { value: (abs / 1_000_000).toFixed(1).replace('.', ','), suffix: 'M' }
  }
  if (abs >= 1_000) {
    return { value: (abs / 1_000).toFixed(1).replace('.', ','), suffix: 'k' }
  }
  return null
}

function fmtBRL(n: number | null | undefined, opts: { compact?: boolean; sign?: boolean } = {}) {
  if (n == null) return '—'
  const { compact = false, sign = false } = opts
  const abs = Math.abs(n)
  const c = compact ? compactSuffix(abs) : null
  let out: string
  if (c) {
    out = `R$ ${c.value}${c.suffix}`
  } else {
    out = new Intl.NumberFormat('pt-BR', {
      style: 'currency', currency: 'BRL',
      minimumFractionDigits: compact ? 0 : 2,
      maximumFractionDigits: compact ? 0 : 2,
    }).format(abs)
  }
  if (sign) return (n >= 0 ? '+' : '−') + out.replace('R$', 'R$ ')
  return n < 0 ? '−' + out : out
}

function fmtUSD(n: number | null | undefined, opts: { compact?: boolean; sign?: boolean } = {}) {
  if (n == null) return '—'
  const { compact = false, sign = false } = opts
  const abs = Math.abs(n)
  const c = compact ? compactSuffix(abs) : null
  let out: string
  if (c) {
    out = `US$ ${c.value}${c.suffix}`
  } else {
    out = new Intl.NumberFormat('en-US', {
      style: 'currency', currency: 'USD',
      minimumFractionDigits: compact ? 0 : 2,
      maximumFractionDigits: compact ? 0 : 2,
    }).format(abs)
  }
  if (sign) return (n >= 0 ? '+' : '−') + out
  return n < 0 ? '−' + out : out
}

function fmtMoney(n: number | null | undefined, ccy: string, opts?: { compact?: boolean; sign?: boolean }) {
  return ccy === 'USD' ? fmtUSD(n, opts) : fmtBRL(n, opts)
}

function fmtNum(n: number | null | undefined, dp = 0) {
  if (n == null) return '—'
  return new Intl.NumberFormat('pt-BR', { minimumFractionDigits: dp, maximumFractionDigits: dp }).format(n)
}

function fmtPct(n: number | null | undefined, dp = 1, sign = false) {
  if (n == null) return '—'
  const v = (n * 100).toFixed(dp)
  return (sign && n > 0 ? '+' : '') + v + '%'
}

function fmtDate(iso: string) {
  return new Intl.DateTimeFormat('pt-BR').format(new Date(iso + (iso.length === 10 ? 'T00:00:00' : '')))
}

function CountryFlag({ country }: { country: string }) {
  const flag = country === 'BR' ? '🇧🇷' : country === 'US' ? '🇺🇸' : '🌐'
  return <span className="text-[11px] leading-none">{flag}</span>
}

// ── Spec 46 — price chart axis helper ───────────────────────────────────────

const PERIOD_LABEL: Record<AssetPriceHistoryPeriod, string> = {
  '6m':  '6 meses',
  '12m': '12 meses',
  '24m': '24 meses',
  'all': 'tudo',
}

const MONTH_SHORT_PT = [
  'jan', 'fev', 'mar', 'abr', 'mai', 'jun',
  'jul', 'ago', 'set', 'out', 'nov', 'dez',
]

function fmtMonthYY(iso: string): string {
  // iso = YYYY-MM-DD
  const [y, m] = iso.split('-')
  return `${MONTH_SHORT_PT[parseInt(m, 10) - 1]}/${y.slice(2)}`
}

function PriceChartAxis({ points }: { points: { date: string }[] }) {
  // Pick 4 evenly spaced anchors out of the series + "hoje" at the end.
  const n = points.length
  if (n < 2) return null
  const idxs = [0, Math.floor(n / 4), Math.floor(n / 2), Math.floor((3 * n) / 4)]
  const anchors = idxs.map(i => fmtMonthYY(points[i].date))
  return (
    <div className="mt-3 flex items-center justify-between text-[10px] uppercase tracking-wider text-gray-500">
      {anchors.map((a, i) => <span key={i}>{a}</span>)}
      <span className="text-indigo-500 dark:text-indigo-400">hoje</span>
    </div>
  )
}

const PTAX = 5.12 // fallback if no fx_rate available

// ── Type label mappings (prototype-faithful) ─────────────────────────────────

const TYPE_MOVEMENT_PALETTE: Record<string, string> = {
  BUY: 'bg-blue-500/15 text-blue-500 dark:text-blue-400',
  SELL: 'bg-red-500/15 text-red-500 dark:text-red-400',
  BONUS: 'bg-emerald-500/15 text-emerald-500 dark:text-emerald-400',
  SUBSCRIPTION: 'bg-violet-500/15 text-violet-500 dark:text-violet-400',
  COME_COTAS: 'bg-amber-500/15 text-amber-500 dark:text-amber-400',
  FULL_REDEMPTION: 'bg-teal-500/15 text-teal-500 dark:text-teal-400',
  SELL_OPEN: 'bg-purple-500/15 text-purple-500 dark:text-purple-400',
  BUY_TO_OPEN: 'bg-purple-500/15 text-purple-500 dark:text-purple-400',
  BUY_TO_CLOSE: 'bg-purple-500/15 text-purple-500 dark:text-purple-400',
  SELL_TO_CLOSE: 'bg-purple-500/15 text-purple-500 dark:text-purple-400',
  EXERCISED: 'bg-amber-500/15 text-amber-500 dark:text-amber-400',
  EXPIRED: 'bg-gray-500/15 text-gray-500 dark:text-gray-400',
}

const TYPE_DISTRIBUTION_PALETTE: Record<string, string> = {
  DIVIDEND: 'bg-amber-500/15 text-amber-500 dark:text-amber-400',
  INTEREST: 'bg-cyan-500/15 text-cyan-500 dark:text-cyan-400',
  JCP: 'bg-emerald-500/15 text-emerald-500 dark:text-emerald-400',
  SECURITIES_LENDING: 'bg-orange-500/15 text-orange-500 dark:text-orange-400',
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
  const [me, setMe] = useState<UserOut | null>(null)
  const [asset, setAsset] = useState<AssetOut | null>(null)
  const [fi, setFi] = useState<FinancialInstitutionOut | null>(null)
  const [account, setAccount] = useState<AccountOut | null>(null)
  const [position, setPosition] = useState<PositionOut | null>(null)
  const [movements, setMovements] = useState<AssetMovementOut[]>([])
  const [distributions, setDistributions] = useState<DistributionOut[]>([])
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
  // Sub-modals já tratam ESC. O hook só fecha o inline confirm.
  useEscapeKey(() => { if (confirmDeactivate) setConfirmDeactivate(null) })

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
        api.listDistributionsForAsset(id, { page: 1, page_size: 200, include_inactive: false })
          .then(p => p.items).catch(() => [] as DistributionOut[]),
      ]))
      .then(([pos, movs, dists]) => {
        setPosition(pos)
        setMovements([...movs].sort((a, b) => b.event_date.localeCompare(a.event_date)))
        setDistributions([...dists].sort((a, b) => b.event_date.localeCompare(a.event_date)))
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
  // Spec 42/45 hotfix — proventos total na moeda nativa do ativo
  // Spec 50 parte 2 — total USD pro footer da tabela de Proventos.
  const distSumUSD = useMemo(
    () => distributions.reduce((s, d) => {
      const fx = d.fx_rate || 0
      const usd = d.currency === 'USD'
        ? d.net_amount
        : (fx > 0 ? d.net_amount / fx : 0)
      return s + usd
    }, 0),
    [distributions],
  )

  // Spec 46 — real price history fetched per (asset, period).
  useEffect(() => {
    if (!me || !id) return
    let cancelled = false
    api.getAssetPriceHistory(id, pricePeriod)
      .then(h => { if (!cancelled) setPriceHistory(h) })
      .catch(() => { if (!cancelled) setPriceHistory(null) })
    return () => { cancelled = true }
  }, [me, id, pricePeriod])

  // Spec 50 — snapshot history (tabela de fechamentos + sparkline).
  useEffect(() => {
    if (!me || !id) return
    let cancelled = false
    setSnapshotHistoryLoading(true)
    api.getAssetSnapshotHistory(id)
      .then(h => { if (!cancelled) setSnapshotHistory(h) })
      .catch(() => { if (!cancelled) setSnapshotHistory(null) })
      .finally(() => { if (!cancelled) setSnapshotHistoryLoading(false) })
    return () => { cancelled = true }
  }, [me, id])

  const priceSeries = useMemo(
    () => priceHistory?.points.map(p => Number(p.unit_price)) ?? [],
    [priceHistory],
  )

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
  const value = price != null && qty ? price * qty : null
  const cost = avg != null && qty ? avg * qty : null
  const pl = value != null && cost != null ? value - cost : null
  const valueBRL = position?.current_value_brl != null ? Number(position.current_value_brl) : null
  const costBRL = position?.total_invested_brl != null ? Number(position.total_invested_brl) : null
  const variation = position?.variation != null ? Number(position.variation) : null
  const rentabilidade = position?.rentabilidade != null ? Number(position.rentabilidade) : null
  const yoc = (costBRL && costBRL > 0) ? distSumBRL / costBRL : null
  const dy = (valueBRL && valueBRL > 0) ? distSumBRL / valueBRL : null
  const lastMovementDate = movements[0]?.event_date

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
                onClick={() => setEditAssetOpen(true)}
                title="Editar dados do ativo (classe, nome, ticker, custodiante…)"
                className="h-8 px-3 inline-flex items-center gap-1.5 rounded-lg text-[12px] bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700 transition-colors"
              >
                <Edit2 className="w-3.5 h-3.5" /> Editar ativo
              </button>
              <button className="h-8 px-3 inline-flex items-center gap-1.5 rounded-lg text-[12px] bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700 transition-colors">
                <Coins className="w-3.5 h-3.5" /> + Provento
              </button>
              <button className="h-8 px-3 inline-flex items-center gap-1.5 rounded-lg text-[12px] bg-indigo-500 hover:bg-indigo-400 text-white transition-colors">
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
                    {ccy === 'USD' && price != null && (
                      <>
                        <span className="mx-1">·</span>
                        <span className="tnum">R$ {(price * PTAX).toFixed(2)}</span>
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
              sub={ccy === 'USD' && pl != null ? fmtBRL(pl * PTAX, { sign: true, compact: true }) : undefined}
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

        {/* Underlying context — OPTION assets only (Spec 34) */}
        {asset.asset_class === 'OPTION' && underlying && (
          <OptionContextCard
            option={asset}
            underlying={underlying}
            position={position}
          />
        )}

        {/* Price chart (Spec 46) — real history from snapshots */}
        {priceSeries.length >= 2 && priceHistory && (
          <Card>
            <SectionTitle action={
              <div className="flex items-center gap-3">
                <span className="text-[11px] text-gray-500">
                  {priceHistory.points.length} fechamentos · {priceHistory.currency}
                </span>
                <GroupingToggle
                  value={pricePeriod}
                  onChange={(v) => setPricePeriod(v as AssetPriceHistoryPeriod)}
                  options={[
                    { id: '6m',  label: '6M'   },
                    { id: '12m', label: '12M'  },
                    { id: '24m', label: '24M'  },
                    { id: 'all', label: 'Tudo' },
                  ]}
                />
              </div>
            }>
              Preço · {PERIOD_LABEL[pricePeriod]}
            </SectionTitle>
            <div className="overflow-hidden -mx-2">
              <Sparkline data={priceSeries} w={1200} h={180} color={klassColor} />
            </div>
            <PriceChartAxis points={priceHistory.points} />
          </Card>
        )}

        {/* Spec 61b — Valuation card (fundamentalista por classe) */}
        <ValuationCard assetId={asset.id} canRefresh={me?.role !== 'member'} />

        {/* Spec 50 — Fechamentos por ativo */}
        <AssetSnapshotsCard
          history={snapshotHistory}
          loading={snapshotHistoryLoading}
          assetId={asset.id}
          movements={movements}
        />

        {/* Lançamentos full table */}
        <Card>
          <SectionTitle action={
            <button
              onClick={() => { setEditingMovement(undefined); setEditingAttachments([]); setMovementComposerOpen(true) }}
              className="h-7 px-2.5 inline-flex items-center gap-1 rounded-md text-[11px] font-medium bg-indigo-500 hover:bg-indigo-400 text-white transition-colors"
            >
              <Plus className="w-3 h-3" /> Novo lançamento
            </button>
          }>
            Lançamentos · {movements.length}
          </SectionTitle>
          {movements.length === 0 ? (
            <div className="text-[12px] text-gray-500 italic py-6 text-center">Sem lançamentos cadastrados.</div>
          ) : (
            <div className="overflow-x-auto -mx-1">
              <table className="w-full text-[12px]">
                <thead>
                  <tr className="text-[10px] uppercase tracking-wider text-gray-500">
                    <th className="text-left font-medium px-2 py-2">Data</th>
                    <th className="text-left font-medium px-2 py-2">Tipo</th>
                    <th className="text-right font-medium px-2 py-2">Qtd</th>
                    <th className="text-right font-medium px-2 py-2">Preço</th>
                    <th className="text-right font-medium px-2 py-2">Taxa</th>
                    <th className="text-right font-medium px-2 py-2">Net</th>
                    <th className="px-2"></th>
                  </tr>
                </thead>
                <tbody>
                  {movements.map(m => {
                    const typeCls = TYPE_MOVEMENT_PALETTE[m.type] || 'bg-gray-500/15 text-gray-500'
                    return (
                      <tr
                        key={m.id}
                        onClick={() => setSelectedMovement(m)}
                        className="border-t border-gray-100 dark:border-gray-800 hover:bg-gray-50 dark:hover:bg-gray-800/30 transition-colors cursor-pointer"
                      >
                        <td className="px-2 py-2 tnum text-gray-400">{fmtDate(m.event_date)}</td>
                        <td className="px-2">
                          <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] uppercase tracking-wider ${typeCls}`}>
                            {m.type_label}
                          </span>
                        </td>
                        <td className="px-2 text-right tnum">
                          {m.quantity != null
                            ? (m.quantity < 1 ? m.quantity.toFixed(4) : fmtNum(m.quantity, m.quantity < 100 ? 2 : 0))
                            : '—'}
                        </td>
                        <td className="px-2 text-right tnum money text-gray-400">{m.unit_price != null ? fmtMoney(m.unit_price, m.currency) : '—'}</td>
                        <td className="px-2 text-right tnum money text-gray-500">{m.fee ? fmtMoney(m.fee, m.currency) : '—'}</td>
                        <td className="px-2 text-right">
                          <div className={`tnum money font-medium ${m.net_amount < 0 ? 'text-red-500 dark:text-red-400' : m.net_amount > 0 ? 'text-emerald-500 dark:text-emerald-400' : 'text-gray-500'}`}>
                            {fmtMoney(m.net_amount, m.currency, { sign: true })}
                          </div>
                        </td>
                        <td className="px-2 text-gray-500"><MoreHorizontal className="w-4 h-4" /></td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </Card>

        {/* Proventos full table */}
        <Card>
          <SectionTitle action={
            <span className="text-[11px] tnum text-gray-500">
              Total{' '}
              <span className="money text-emerald-500 dark:text-emerald-400 font-medium">
                {fmtBRL(distSumBRL, { compact: true })}
              </span>
              <span className="mx-1 text-gray-400">·</span>
              <span className="money text-emerald-500 dark:text-emerald-400 font-medium">
                {fmtUSD(distSumUSD, { compact: true })}
              </span>
            </span>
          }>
            Proventos · {distributions.length}
          </SectionTitle>
          {distributions.length === 0 ? (
            <div className="text-[12px] text-gray-500 italic py-6 text-center">Sem proventos cadastrados.</div>
          ) : (
            <div className="overflow-x-auto -mx-1">
              <table className="w-full text-[12px]">
                <thead>
                  <tr className="text-[10px] uppercase tracking-wider text-gray-500">
                    <th className="text-left font-medium px-2 py-2">Data</th>
                    <th className="text-left font-medium px-2 py-2">Tipo</th>
                    <th className="text-right font-medium px-2 py-2">Bruto</th>
                    <th className="text-right font-medium px-2 py-2">IR</th>
                    <th className="text-right font-medium px-2 py-2">Líquido</th>
                    <th className="text-right font-medium px-2 py-2">USD</th>
                    <th className="px-2"></th>
                  </tr>
                </thead>
                <tbody>
                  {distributions.map(d => {
                    const typeCls = TYPE_DISTRIBUTION_PALETTE[d.type] || 'bg-gray-500/15 text-gray-500'
                    const fx = d.fx_rate || 0
                    const usdNet = d.currency === 'USD'
                      ? d.net_amount
                      : (fx > 0 ? d.net_amount / fx : null)
                    return (
                      <tr key={d.id} className="border-t border-gray-100 dark:border-gray-800 hover:bg-gray-50 dark:hover:bg-gray-800/30 transition-colors cursor-pointer">
                        <td className="px-2 py-2 tnum text-gray-400">{fmtDate(d.event_date)}</td>
                        <td className="px-2">
                          <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] uppercase tracking-wider ${typeCls}`}>
                            {d.type_label}
                          </span>
                        </td>
                        <td className="px-2 text-right tnum money text-gray-400">{fmtMoney(d.gross_amount, d.currency)}</td>
                        <td className="px-2 text-right tnum money text-amber-500 dark:text-amber-400">{d.tax && d.tax > 0 ? '−' + fmtMoney(d.tax, d.currency) : '—'}</td>
                        <td className="px-2 text-right">
                          <div className="tnum money font-medium text-emerald-500 dark:text-emerald-400">{fmtMoney(d.net_amount, d.currency, { sign: true })}</div>
                        </td>
                        <td className="px-2 text-right tnum money text-gray-500 dark:text-gray-400" title={fx > 0 ? `PTAX ${fx.toFixed(4)}` : 'sem fx_rate'}>
                          {usdNet == null ? '—' : fmtUSD(usdNet)}
                        </td>
                        <td className="px-2 text-gray-500"><MoreHorizontal className="w-4 h-4" /></td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </Card>

        {/* Spec 50 parte 2 — gráfico de proventos mensais */}
        {distributions.length >= 2 && (
          <AssetDistributionsChart distributions={distributions} />
        )}

        {/* Open options card */}
        {asset.asset_class !== 'OPTION' && (
          <OpenOptionsCard
            key={optionsRefresh}
            underlyingId={asset.id}
            underlyingTicker={asset.ticker || asset.name}
            onAction={() => setOptionsRefresh(n => n + 1)}
            onAddOption={() => setOptionModalOpen(true)}
          />
        )}

        {/* Detalhes / metadata */}
        <Card>
          <SectionTitle>Detalhes</SectionTitle>
          <dl className="grid grid-cols-2 lg:grid-cols-4 gap-x-6 gap-y-3 text-[12px]">
            <Detail label="Ticker" value={asset.ticker || '—'} mono />
            <Detail label="CNPJ" value={asset.cnpj || '—'} mono />
            <Detail label="Classe">
              <ClassBadge klass={klass} size="xs" withDot={false} />
            </Detail>
            <Detail label="País">
              <span className="inline-flex items-center gap-1.5">
                <CountryFlag country={asset.country} />
                <span>{asset.country === 'BR' ? 'Brasil' : asset.country === 'US' ? 'EUA' : asset.country}</span>
              </span>
            </Detail>
            <Detail label="Moeda">
              <CcyPill ccy={ccy} />
            </Detail>
            <Detail label="Custodiante" value={fi?.short_name || '—'} />
            <Detail label="Conta" value={account?.name || '—'} />
            <Detail label="Status">
              {asset.is_active
                ? <span className="text-emerald-500 dark:text-emerald-400">Ativo</span>
                : <span className="text-gray-500">Zerado</span>}
            </Detail>
            <Detail label="Total investido" value={fmtBRL(costBRL, { compact: true })} tnum money />
            <Detail label="Total recebido" value={fmtBRL(distSumBRL, { compact: true })} tnum money tone="positive" />
            <Detail label="Lançamentos" value={String(movements.length)} tnum />
            <Detail label="Último lançamento" value={lastMovementDate ? fmtDate(lastMovementDate) : '—'} tnum />
          </dl>
        </Card>
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

function KpiTile({
  label, value, sub, intent, cornerDot,
}: {
  label: string
  value: string
  sub?: React.ReactNode
  intent?: 'positive' | 'negative'
  cornerDot?: { color: string; title?: string }
}) {
  const intentColor =
    intent === 'negative' ? 'text-red-500 dark:text-red-400'
    : intent === 'positive' ? 'text-emerald-500 dark:text-emerald-400'
    : ''
  return (
    <div className="relative px-4 py-3 rounded-xl bg-gray-50 dark:bg-gray-800/40 border border-gray-200 dark:border-gray-800">
      {cornerDot && (
        <span
          className="absolute top-2 right-2 w-1.5 h-1.5 rounded-full"
          style={{ background: cornerDot.color }}
          title={cornerDot.title}
          aria-label={cornerDot.title}
          data-testid="kpi-dot"
        />
      )}
      <div className="text-[11px] uppercase tracking-wider font-medium text-gray-500 dark:text-gray-400">{label}</div>
      <div className={`mt-1 text-lg font-semibold tnum money flex items-center gap-2 ${intentColor}`}>
        {value}
      </div>
      {sub && <div className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">{sub}</div>}
    </div>
  )
}

function Detail({
  label, value, children, mono, tnum, money, tone,
}: {
  label: string
  value?: string
  children?: React.ReactNode
  mono?: boolean
  tnum?: boolean
  money?: boolean
  tone?: 'positive' | 'negative'
}) {
  const toneCls = tone === 'positive' ? 'text-emerald-500 dark:text-emerald-400'
    : tone === 'negative' ? 'text-red-500 dark:text-red-400'
    : 'text-gray-900 dark:text-white'
  const cls = `mt-0.5 ${mono ? 'font-mono' : ''} ${tnum ? 'tnum' : ''} ${money ? 'money' : ''} ${toneCls}`.trim()
  return (
    <div>
      <dt className="text-[10px] uppercase tracking-wider text-gray-500 dark:text-gray-400">{label}</dt>
      <dd className={cls}>{children ?? value}</dd>
    </div>
  )
}
