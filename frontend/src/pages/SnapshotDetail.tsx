/* Spec 35 — /snapshots/{ym} — Mirrors prototypes/index.html
 * FechamentoDetailPage (~6983) section-by-section. Adaptations vs the
 * prototype, locked by the user on 2026-05-25:
 *   - The PTAX tile stays a dedicated KPI (the user explicitly asked
 *     us to keep it separate from the "Patrimônio fim do mês" tile).
 *   - "Patrimônio fim do mês" KPI renders the full number without
 *     centavos (e.g. "R$ 12.468.724"), per user request.
 *   - "Origem dos dados" card uses live PendencyReason counts from
 *     the backend rather than the prototype's mock SOURCES enum.
 */
import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'

import { fmtBRL, fmtMoney, fmtUSD } from '../lib/money'
import { downloadCsv, fmtCsvDecimal } from '../lib/csv'
import {
  ArrowLeft, ArrowRight, ChevronRight, Download, Loader2, Plus, RotateCcw,
} from 'lucide-react'

import {
  api,
  type AssetOut,
  type DistributionOut,
  type DriftEntryOut,
  type FinancialInstitutionOut,
  type SnapshotItemOut,
  type SnapshotOut,
  type SnapshotPendencyOut,
  type SyntheticPremiumOut,
  type UserOut,
} from '../lib/api'
import AppLayout from '../components/AppLayout'
import AddSnapshotAssetModal from '../components/AddSnapshotAssetModal'
import DistributionEditModal from '../components/DistributionEditModal'
import AssetFilterBar from '../components/AssetFilterBar'
import MoMDeltaBlock from '../components/MoMDeltaBlock'
import PendencyPanel from '../components/PendencyPanel'
import SnapshotDriftPanel from '../components/SnapshotDriftPanel'
import SnapshotItemEditModal from '../components/SnapshotItemEditModal'
import StatusPill from '../components/StatusPill'
import { Card, ClassBadge, FILogo, MultiChips, SearchInput, SectionTitle } from '../components/ui'
import { KLASS, collapsedOf, fiTokenFor, type CollapsedClassCode } from '../lib/tokens'

const MONTH_NAMES_LONG = [
  'Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho',
  'Julho', 'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro',
]
const MONTH_NAMES_SHORT = [
  'Jan', 'Fev', 'Mar', 'Abr', 'Mai', 'Jun',
  'Jul', 'Ago', 'Set', 'Out', 'Nov', 'Dez',
]
const WEEKDAYS = [
  'Domingo', 'Segunda', 'Terça', 'Quarta', 'Quinta', 'Sexta', 'Sábado',
]

function ymLabelLong(ym: string): string {
  const [y, m] = ym.split('-')
  return `${MONTH_NAMES_LONG[parseInt(m, 10) - 1]} ${y}`
}
function ymLabelShort(ym: string): string {
  const [y, m] = ym.split('-')
  return `${MONTH_NAMES_SHORT[parseInt(m, 10) - 1]}/${y.slice(2)}`
}
function fmtDateBR(iso: string): string {
  return new Date(iso + (iso.length === 10 ? 'T00:00:00' : '')).toLocaleDateString('pt-BR')
}
function dayOfWeekPT(iso: string): string {
  const d = new Date(iso + 'T00:00:00')
  return WEEKDAYS[d.getDay()]
}
// Formatters centralizados em lib/money — M/k em vez de mi/mil.

// ── reason → bucket counts for the Origem card ──────────────────────────────
function bucketCounts(
  items: SnapshotItemOut[],
  pendencies: SnapshotPendencyOut[],
  assetById: Map<string, AssetOut>,
) {
  let api_ok = 0, manual_done = 0, api_failed = 0, manual_pending = 0, upload_pending = 0
  const openByAsset = new Map<string, SnapshotPendencyOut>()
  for (const p of pendencies) if (!p.resolved_at) openByAsset.set(p.asset_id, p)
  for (const it of items) {
    const asset = assetById.get(it.asset_id)
    if (!asset) continue
    const open = openByAsset.get(it.asset_id)
    if (open) {
      if (open.reason === 'API_FAILED' || open.reason === 'STALE_PRICE') api_failed++
      else if (open.reason === 'UPLOAD_REQUIRED') upload_pending++
      else manual_pending++
    } else if (asset.price_source === 'MANUAL' || asset.price_source == null) {
      manual_done++
    } else {
      api_ok++
    }
  }
  return { api_ok, manual_done, api_failed, manual_pending, upload_pending }
}

// ── HBar matching prototype ────────────────────────────────────────────────
function HBar({ value, max, color, height = 6 }: { value: number; max: number; color: string; height?: number }) {
  const pct = max > 0 ? Math.min(100, (value / max) * 100) : 0
  return (
    <div className="w-full rounded-full overflow-hidden bg-gray-200 dark:bg-gray-800" style={{ height }}>
      <div className="h-full rounded-full" style={{ width: `${pct}%`, background: color }} />
    </div>
  )
}


export default function SnapshotDetail() {
  const { ym } = useParams<{ ym: string }>()
  const navigate = useNavigate()
  const [me, setMe] = useState<UserOut | null>(null)
  const [snap, setSnap] = useState<SnapshotOut | null>(null)
  const [items, setItems] = useState<SnapshotItemOut[]>([])
  const [pendencies, setPendencies] = useState<SnapshotPendencyOut[]>([])
  const [assets, setAssets] = useState<AssetOut[]>([])
  const [institutions, setInstitutions] = useState<FinancialInstitutionOut[]>([])
  const [distributions, setDistributions] = useState<DistributionOut[]>([])
  const [syntheticPremiums, setSyntheticPremiums] = useState<SyntheticPremiumOut[]>([])
  const [allSnaps, setAllSnaps] = useState<SnapshotOut[]>([])
  const [prevItems, setPrevItems] = useState<SnapshotItemOut[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [addAssetOpen, setAddAssetOpen] = useState(false)
  const [syncing, setSyncing] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [reopening, setReopening] = useState(false)
  const [syncToast, setSyncToast] = useState<{
    text: string; tone: 'success' | 'info' | 'error'
  } | null>(null)
  const [editingDistribution, setEditingDistribution] = useState<DistributionOut | null>(null)
  // Filtros + sort da tabela "Eventos do mês" (#3).
  const [eventsSearch, setEventsSearch] = useState('')
  const [eventsTypeSel, setEventsTypeSel] = useState<string[]>([])
  type EventsSortKey = 'event_date' | 'label_primary' | 'type' | 'gross_brl' | 'net_native'
  const [eventsSort, setEventsSort] = useState<{ key: EventsSortKey; dir: 'asc' | 'desc' }>(
    { key: 'event_date', dir: 'asc' },
  )
  // Spec 51 Bloco 3 — entradas de "divergência aceita" do audit log.
  const [drift, setDrift] = useState<DriftEntryOut[]>([])

  useEffect(() => {
    api.me().then(setMe).catch(() => navigate('/login'))
  }, [navigate])

  useEffect(() => {
    if (!me || !ym) return
    let cancelled = false
    setLoading(true); setError('')

    api.listSnapshots()
      .then(async list => {
        if (cancelled) return
        setAllSnaps(list)
        const match = list.find(s => s.period_end_date.startsWith(ym))
        if (!match) { setError(`Sem snapshot para ${ym}.`); setLoading(false); return }
        setSnap(match)
        const [its, pens, as, fis, distPage, drifts] = await Promise.all([
          api.listSnapshotItems(match.id),
          api.listSnapshotPendencies(match.id),
          api.listAssets({ include_inactive: true }),
          api.listFinancialInstitutions().catch(() => [] as FinancialInstitutionOut[]),
          api.listDistributions({
            from: `${ym}-01`,
            to: match.period_end_date,
            page_size: 200,
            include_synthetic: true,
          }),
          api.listSnapshotDrift(match.id).catch(() => []),
        ])
        if (cancelled) return
        setItems(its)
        setPendencies(pens)
        setAssets(as)
        setInstitutions(fis)
        setDistributions(distPage.items)
        setSyntheticPremiums(distPage.synthetic_premiums ?? [])
        setDrift(drifts)
      })
      .catch(e => setError(e instanceof Error ? e.message : 'Erro'))
      .finally(() => { if (!cancelled) setLoading(false) })

    return () => { cancelled = true }
  }, [me, ym])

  // Prev snapshot for MoM + movers
  const sortedSnaps = useMemo(
    () => [...allSnaps].sort((a, b) => a.period_end_date.localeCompare(b.period_end_date)),
    [allSnaps],
  )
  const idx = useMemo(
    () => snap ? sortedSnaps.findIndex(s => s.id === snap.id) : -1,
    [snap, sortedSnaps],
  )
  const prevSnap = idx > 0 ? sortedSnaps[idx - 1] : null
  const nextSnap = idx >= 0 && idx < sortedSnaps.length - 1 ? sortedSnaps[idx + 1] : null
  const prevYm = prevSnap ? prevSnap.period_end_date.slice(0, 7) : null
  const nextYm = nextSnap ? nextSnap.period_end_date.slice(0, 7) : null

  useEffect(() => {
    if (!prevSnap) { setPrevItems([]); return }
    api.listSnapshotItems(prevSnap.id).then(setPrevItems).catch(() => setPrevItems([]))
  }, [prevSnap])

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

  async function refreshPendencies() {
    if (!snap) return
    // Refazer items + assets + distributions + sintéticos após Apply.
    // Spec 49 hotfix #7 fixou items; agora #2 (auto-refresh) garante que
    // proventos novos do extrato (Distribution + OPTION_PREMIUM sintético
    // via SELL_OPEN) também aparecem sem refresh manual.
    const ymStr = snap.period_end_date.slice(0, 7)
    const [pens, fresh, its, as_, distPage] = await Promise.all([
      api.listSnapshotPendencies(snap.id),
      api.listSnapshots(),
      api.listSnapshotItems(snap.id),
      api.listAssets({ include_inactive: true }),
      api.listDistributions({
        from: `${ymStr}-01`,
        to: snap.period_end_date,
        page_size: 200,
        include_synthetic: true,
      }),
    ])
    setPendencies(pens); setAllSnaps(fresh)
    setSnap(fresh.find(s => s.id === snap.id) ?? snap)
    setItems(its); setAssets(as_)
    setDistributions(distPage.items)
    setSyntheticPremiums(distPage.synthetic_premiums ?? [])
  }

  function exportEventosCsv() {
    if (!snap) return
    const ymStr = snap.period_end_date.slice(0, 7)
    const header = [
      'Data', 'Ativo', 'Tipo', 'Moeda Nativa',
      'Bruto (BRL)', 'Bruto (USD)', 'IRRF (Nativo)', 'Líquido (Nativo)',
      'Custodiante',
    ]
    const lines: (string | number | null)[][] = [header]
    for (const r of eventRows) {
      const fiName = r.id.startsWith('synthetic:')
        ? (syntheticPremiums.find(p => p.id === r.id)?.financial_institution_name ?? '')
        : (distributions.find(d => d.id === r.id)?.financial_institution_name ?? '')
      const typeLabel = TYPE_META[r.type]?.label ?? r.type
      lines.push([
        r.event_date,
        r.label_primary + (r.label_secondary ? ` (${r.label_secondary})` : ''),
        typeLabel,
        r.currency,
        fmtCsvDecimal(r.gross_brl),
        fmtCsvDecimal(r.gross_usd, 2),
        fmtCsvDecimal(r.tax_native),
        fmtCsvDecimal(r.net_native),
        fiName,
      ])
    }
    downloadCsv(`proventos-${ymStr}.csv`, lines)
  }

  function exportPositionsCsv() {
    if (!snap) return
    const ymStr = snap.period_end_date.slice(0, 7)
    const header = [
      'Ativo', 'Nome', 'Classe', 'Custodiante', 'Moeda Nativa',
      'Quantidade', 'Preço Unitário', 'Valor Total (BRL)', 'Valor Total (USD)',
      '% Portfólio',
    ]
    const lines: (string | number | null)[][] = [header]
    for (const it of filteredPositions) {
      const a = assetById.get(it.asset_id)
      if (!a) continue
      const fi = fiById.get(a.financial_institution_id)
      const valueBRL = it.market_value_brl != null ? Number(it.market_value_brl) : null
      const valueUSD = it.market_value_usd != null
        ? Number(it.market_value_usd)
        : (valueBRL != null && fxRate && fxRate > 0 ? valueBRL / fxRate : null)
      const pct = valueBRL != null && totalBRL > 0 ? (valueBRL / totalBRL) * 100 : null
      lines.push([
        a.ticker ?? a.name,
        a.name,
        collapsedOf(a.asset_class),
        fi?.short_name ?? a.financial_institution_name ?? '',
        a.currency,
        fmtCsvDecimal(Number(it.quantity), 4),
        fmtCsvDecimal(it.unit_price != null ? Number(it.unit_price) : null, 4),
        fmtCsvDecimal(valueBRL),
        fmtCsvDecimal(valueUSD),
        fmtCsvDecimal(pct),
      ])
    }
    downloadCsv(`posicoes-${ymStr}.csv`, lines)
  }

  async function handleConfirm() {
    if (!snap || confirming) return
    setConfirming(true); setSyncToast(null)
    try {
      const updated = await api.confirmSnapshot(snap.id)
      setSnap(updated)
      window.dispatchEvent(new CustomEvent('snapshot-status-changed'))
      setSyncToast({ text: 'Fechamento confirmado.', tone: 'success' })
    } catch (e) {
      setSyncToast({
        text: e instanceof Error ? e.message : 'Erro ao confirmar fechamento',
        tone: 'error',
      })
    } finally {
      setConfirming(false)
    }
  }

  async function handleReopen() {
    if (!snap || reopening) return
    const reason = window.prompt('Motivo da reabertura:')
    if (!reason) return
    setReopening(true); setSyncToast(null)
    try {
      const updated = await api.reopenSnapshot(snap.id, reason)
      setSnap(updated)
      const [pens, its] = await Promise.all([
        api.listSnapshotPendencies(snap.id),
        api.listSnapshotItems(snap.id),
      ])
      setPendencies(pens)
      setItems(its)
      window.dispatchEvent(new CustomEvent('snapshot-status-changed'))
      setSyncToast({ text: 'Fechamento reaberto.', tone: 'success' })
    } catch (e) {
      setSyncToast({
        text: e instanceof Error ? e.message : 'Erro ao reabrir fechamento',
        tone: 'error',
      })
    } finally {
      setReopening(false)
    }
  }

  async function handleSyncItems() {
    if (!snap || syncing) return
    setSyncing(true); setSyncToast(null)
    try {
      const result = await api.syncSnapshotItems(snap.id)
      if (result.items_added === 0) {
        setSyncToast({
          text: 'Nenhum ativo faltando — snapshot já está completo.',
          tone: 'info',
        })
      } else {
        // Refresh items + pendencies after server side-effects.
        const [its, pens] = await Promise.all([
          api.listSnapshotItems(snap.id),
          api.listSnapshotPendencies(snap.id),
        ])
        setItems(its)
        setPendencies(pens)
        setSyncToast({
          text:
            `${result.items_added} ativo(s) adicionado(s).`
            + (result.pendencies_added > 0
              ? ` ${result.pendencies_added} pendência(s) criada(s) — preencha os saldos.`
              : ''),
          tone: 'success',
        })
      }
    } catch (e) {
      setSyncToast({
        text: e instanceof Error ? e.message : 'Erro',
        tone: 'error',
      })
    } finally {
      setSyncing(false)
    }
  }

  // Auto-clear toast after 6s.
  useEffect(() => {
    if (!syncToast) return
    const t = window.setTimeout(() => setSyncToast(null), 6000)
    return () => window.clearTimeout(t)
  }, [syncToast])

  // Derived
  const totalBRL = snap ? Number(snap.total_value_brl) : 0
  const totalUSD = snap ? Number(snap.total_value_usd) : 0
  const fxRate = snap?.fx_rate_usd_brl ? Number(snap.fx_rate_usd_brl) : null

  const prevTotal = prevSnap ? Number(prevSnap.total_value_brl) : null
  const prevTotalUSD = prevSnap ? Number(prevSnap.total_value_usd) : null
  const momDelta = prevTotal && prevTotal > 0
    ? (totalBRL - prevTotal) / prevTotal
    : null
  const momDeltaBRL = prevTotal != null ? totalBRL - prevTotal : null
  // Spec 41 formula B: Δ$ = snap.total_usd − prev.total_usd. Each total
  // was stamped with its own PTAX, so this captures cambial drift.
  const momDeltaUSD = prevTotalUSD != null ? totalUSD - prevTotalUSD : null

  const proventosRealBRL = distributions.reduce(
    (s, d) => s + Number(d.net_amount) * Number(d.fx_rate || 1),
    0,
  )
  const proventosSintBRL = syntheticPremiums.reduce(
    (s, p) => s + Number(p.net_amount) * Number(p.fx_rate || 1),
    0,
  )
  const proventosBRL = proventosRealBRL + proventosSintBRL
  const proventosCount = distributions.length + syntheticPremiums.length
  const yieldPct = totalBRL > 0 ? proventosBRL / totalBRL : 0

  const byClass = useMemo(() => {
    const acc: Record<string, number> = {}
    for (const it of items) {
      const a = assetById.get(it.asset_id)
      if (!a) continue
      const k = collapsedOf(a.asset_class)
      acc[k] = (acc[k] || 0) + Number(it.market_value_brl ?? 0)
    }
    return acc
  }, [items, assetById])

  const proventosByType = useMemo(() => {
    const acc: Record<string, number> = {}
    for (const d of distributions) {
      const k = d.type
      acc[k] = (acc[k] || 0) + Number(d.net_amount) * Number(d.fx_rate || 1)
    }
    for (const p of syntheticPremiums) {
      acc.OPTION_PREMIUM =
        (acc.OPTION_PREMIUM || 0) + Number(p.net_amount) * Number(p.fx_rate || 1)
    }
    return acc
  }, [distributions, syntheticPremiums])

  // Linhas normalizadas pra tabela "Eventos do mês" — Distribution real +
  // OPTION_PREMIUM sintético derivado de AssetMovement SELL_OPEN/BUY_TO_CLOSE.
  interface EventRow {
    id: string
    event_date: string
    label_primary: string   // ticker
    label_secondary: string | null
    type: string
    gross_brl: number       // bruto convertido em BRL
    gross_usd: number       // bruto convertido em USD
    tax_native: number | null
    net_native: number
    currency: 'BRL' | 'USD' // moeda nativa do evento (pra IRRF/Líquido)
  }
  const eventRows = useMemo<EventRow[]>(() => {
    const rows: EventRow[] = []
    const ptaxFallback = fxRate && fxRate > 0 ? fxRate : 0
    const toBRL = (amount: number, currency: 'BRL' | 'USD', rowFx: number) => {
      if (currency === 'BRL') return amount
      const fx = rowFx || ptaxFallback
      return fx > 0 ? amount * fx : amount
    }
    const toUSD = (amount: number, currency: 'BRL' | 'USD', rowFx: number) => {
      if (currency === 'USD') return amount
      const fx = rowFx || ptaxFallback
      return fx > 0 ? amount / fx : 0
    }
    for (const d of distributions) {
      const fx = Number(d.fx_rate || 1)
      rows.push({
        id: d.id,
        event_date: d.event_date,
        label_primary: d.asset_ticker ?? d.asset_name ?? '—',
        label_secondary: d.asset_ticker ? d.asset_name : null,
        type: d.type,
        gross_brl: toBRL(d.gross_amount, d.currency, fx),
        gross_usd: toUSD(d.gross_amount, d.currency, fx),
        tax_native: d.tax,
        net_native: d.net_amount,
        currency: d.currency,
      })
    }
    for (const p of syntheticPremiums) {
      const fx = Number(p.fx_rate || 1)
      rows.push({
        id: p.id,
        event_date: p.event_date,
        label_primary: p.option_ticker ?? p.underlying_ticker ?? '—',
        label_secondary: p.side === 'SELL_OPEN' ? 'Venda pra abrir' : 'Compra pra fechar',
        type: 'OPTION_PREMIUM',
        gross_brl: toBRL(p.gross_amount, p.currency, fx),
        gross_usd: toUSD(p.gross_amount, p.currency, fx),
        tax_native: null,
        net_native: p.net_amount,
        currency: p.currency,
      })
    }
    return rows.sort((a, b) => a.event_date.localeCompare(b.event_date))
  }, [distributions, syntheticPremiums, fxRate])

  const filteredEventRows = useMemo(() => {
    const q = eventsSearch.trim().toLowerCase()
    const filtered = eventRows.filter(r => {
      if (eventsTypeSel.length > 0 && !eventsTypeSel.includes(r.type)) return false
      if (q) {
        const hay = (
          r.label_primary + ' ' + (r.label_secondary ?? '') + ' ' + r.type
        ).toLowerCase()
        if (!hay.includes(q)) return false
      }
      return true
    })
    const { key, dir } = eventsSort
    const sign = dir === 'asc' ? 1 : -1
    return [...filtered].sort((a, b) => {
      const av = a[key] as string | number
      const bv = b[key] as string | number
      if (typeof av === 'number' && typeof bv === 'number') return sign * (av - bv)
      return sign * String(av).localeCompare(String(bv))
    })
  }, [eventRows, eventsSearch, eventsTypeSel, eventsSort])

  function toggleEventsSort(key: EventsSortKey) {
    setEventsSort(prev =>
      prev.key === key
        ? { key, dir: prev.dir === 'asc' ? 'desc' : 'asc' }
        : { key, dir: 'asc' },
    )
  }

  // Top movers (Spec 45 fix 2026-05-30) — use UNIT PRICE change, not
  // market-value change. Market value mistura 3 efeitos: variação de
  // preço (rendimento real), aporte/resgate (qty muda), e câmbio
  // (pra USD). Pra "Maiores altas / quedas · MoM" só interessa o
  // primeiro. Native unit_price também elimina o efeito cambial.
  // CASH/FGTS ficam fora — unit_price é o próprio saldo, não tem
  // sentido falar em "rendimento" deles aqui.
  const movers = useMemo(() => {
    if (prevItems.length === 0) return [] as { asset: AssetOut; valueBRL: number; pct: number }[]
    const prevPrice = new Map<string, number>()
    for (const it of prevItems) {
      if (it.unit_price != null) prevPrice.set(it.asset_id, Number(it.unit_price))
    }
    const rows: { asset: AssetOut; valueBRL: number; pct: number }[] = []
    for (const it of items) {
      const a = assetById.get(it.asset_id)
      if (!a) continue
      if (a.asset_class === 'CASH' || a.asset_class === 'FGTS') continue
      const nowPrice = it.unit_price != null ? Number(it.unit_price) : null
      const prev = prevPrice.get(it.asset_id) ?? null
      if (!nowPrice || !prev || nowPrice <= 0 || prev <= 0) continue
      const pct = (nowPrice - prev) / prev
      // Threshold: only show real movers (|pct| ≥ 0.1%). Filters out
      // noise from rounding + stable-price assets that would otherwise
      // dilute the top-5.
      if (Math.abs(pct) < 0.001) continue
      // Sanity guardrail: |pct| > 70% num único mês é quase certo erro de
      // unit basis (ex.: BTC stored como BRL num mês e USD no outro, ou
      // PRIO3-problem onde unit_price reseta após FULL_REDEMPTION). Filtra
      // até a gente corrigir os dados.
      if (Math.abs(pct) > 0.7) continue
      const valueBRL = Number(it.market_value_brl ?? 0)
      rows.push({ asset: a, valueBRL, pct })
    }
    return rows.sort((a, b) => b.pct - a.pct)
  }, [items, prevItems, assetById])
  const topUp = movers.slice(0, 5)
  const topDown = movers.slice(-5).reverse()

  const isPending = snap?.status === 'IN_REVIEW'
  const [editingItem, setEditingItem] = useState<SnapshotItemOut | null>(null)

  // Filtros da seção "Posições Congeladas" — espelham os filtros da página
  // /ativos via AssetFilterBar (sessão 2026-06-06). Estado mantido aqui;
  // o componente é só UI.
  const [posSearch, setPosSearch] = useState('')
  const [posKlassSel, setPosKlassSel] = useState<string[]>([])
  const [posCountrySel, setPosCountrySel] = useState<string[]>([])
  const [posFiSel, setPosFiSel] = useState<string[]>([])
  // "Incluir sem valor" — items que ainda não têm market_value_brl
  // (USD treasuries não-resolvidos, pendências em aberto). Default ON
  // pra não esconder pendências por engano.
  const [posIncludeNoValue, setPosIncludeNoValue] = useState(true)

  // Sort by the snapshot ITEM's own updated_at (when this row, in this
  // snapshot, was last touched) — NOT by asset.price_updated_at, which
  // gets stomped by the dashboard's bulk price refresh and produces
  // random-looking order. Desc → just-edited rows float to the top.
  const sortedPositions = useMemo(
    () => [...items].sort((a, b) => b.updated_at.localeCompare(a.updated_at)),
    [items],
  )

  const filteredPositions = useMemo(() => {
    const q = posSearch.trim().toLowerCase()
    return sortedPositions.filter(it => {
      const a = assetById.get(it.asset_id)
      if (!a) return false
      if (q && !(a.ticker?.toLowerCase().includes(q) ?? false) && !a.name.toLowerCase().includes(q)) return false
      if (posKlassSel.length && !posKlassSel.includes(collapsedOf(a.asset_class))) return false
      if (posCountrySel.length && !posCountrySel.includes(a.country)) return false
      if (posFiSel.length && !posFiSel.includes(a.financial_institution_id)) return false
      if (!posIncludeNoValue) {
        const hasValue = it.market_value_brl != null && Number(it.market_value_brl) > 0
        if (!hasValue) return false
      }
      return true
    })
  }, [sortedPositions, assetById, posSearch, posKlassSel, posCountrySel, posFiSel, posIncludeNoValue])

  const posFiOpts = useMemo(() => {
    const present = new Set<string>()
    for (const it of items) {
      const a = assetById.get(it.asset_id)
      if (a) present.add(a.financial_institution_id)
    }
    return institutions
      .filter(fi => present.has(fi.id))
      .map(fi => ({ id: fi.id, label: fi.short_name, color: fiTokenFor(fi.logo_slug, fi.short_name).color }))
  }, [items, institutions, assetById])

  const [showAllPositions, setShowAllPositions] = useState(false)
  const sources = useMemo(
    () => bucketCounts(items, pendencies, assetById),
    [items, pendencies, assetById],
  )
  const pendingTotal = sources.api_failed + sources.manual_pending + sources.upload_pending
  const resolvedAssets = sources.api_ok + sources.manual_done
  const totalAssetsCount = items.length

  if (!me) return null

  return (
    <AppLayout user={me}>
      <div className="space-y-6">
        {/* ── 1. Header (prototype line 7042) ────────────────────────── */}
        <div className="flex items-start justify-between gap-3 flex-wrap">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <Link
                to="/snapshots"
                className="text-[11px] text-gray-500 hover:text-indigo-500 inline-flex items-center gap-1"
              >
                <ArrowLeft className="w-3 h-3" /> Voltar pra fechamentos
              </Link>
            </div>
            <div className="flex items-center gap-3 flex-wrap">
              <h1 className="text-2xl font-semibold tracking-tight">
                {ym ? ymLabelLong(ym) : ''}
              </h1>
              {snap && <StatusPill status={snap.status} />}
            </div>
            <div className="text-[12px] text-gray-500 mt-1">
              {snap && (
                <>
                  Posições congeladas em{' '}
                  <span className="text-gray-700 dark:text-gray-300">
                    {fmtDateBR(snap.period_end_date)} ({dayOfWeekPT(snap.period_end_date)})
                  </span>
                  {snap.closed_at && (
                    <> · fechado em {new Date(snap.closed_at).toLocaleDateString('pt-BR')}</>
                  )}
                </>
              )}
            </div>
          </div>

          <div className="flex items-center gap-2 flex-wrap">
            {prevYm && (
              <Link
                to={`/snapshots/${prevYm}`}
                className="h-8 px-2.5 inline-flex items-center gap-1 rounded-lg text-[12px] bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700"
              >
                <ArrowLeft className="w-3 h-3" /> {ymLabelShort(prevYm)}
              </Link>
            )}
            {nextYm && (
              <Link
                to={`/snapshots/${nextYm}`}
                className="h-8 px-2.5 inline-flex items-center gap-1 rounded-lg text-[12px] bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700"
              >
                {ymLabelShort(nextYm)} <ArrowRight className="w-3 h-3" />
              </Link>
            )}
            <button
              disabled
              title="Exportar PDF — em breve"
              className="h-8 px-3 inline-flex items-center gap-1.5 rounded-lg text-[12px] bg-gray-100 dark:bg-gray-800 text-gray-400 dark:text-gray-600 cursor-not-allowed"
            >
              <Download className="w-3.5 h-3.5" /> Exportar PDF
            </button>
            {snap && isPending && (
              <>
                <button
                  onClick={handleSyncItems}
                  disabled={syncing}
                  title="Adiciona ativos que deveriam estar no fechamento mas não estão (ex.: previdência/fundo lançado depois)"
                  className="h-8 px-3 inline-flex items-center gap-1.5 rounded-lg text-[12px] bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700 disabled:opacity-60 disabled:cursor-not-allowed"
                  data-testid="snapshot-sync-items"
                >
                  {syncing
                    ? <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Sincronizando…</>
                    : <><RotateCcw className="w-3.5 h-3.5" /> Sincronizar ativos</>}
                </button>
                <button
                  onClick={() => setAddAssetOpen(true)}
                  title="Adicionar manualmente um ativo ao fechamento"
                  className="h-8 px-3 inline-flex items-center gap-1.5 rounded-lg text-[12px] bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700"
                  data-testid="snapshot-add-item"
                >
                  <Plus className="w-3.5 h-3.5" /> Adicionar ativo
                </button>
              </>
            )}
            {snap && !isPending && (
              <button
                onClick={handleReopen}
                disabled={reopening}
                className="h-8 px-3 inline-flex items-center gap-1.5 rounded-lg text-[12px] border border-amber-300 dark:border-amber-700 text-amber-700 dark:text-amber-400 hover:bg-amber-50 dark:hover:bg-amber-900/20 disabled:opacity-60 disabled:cursor-wait"
              >
                {reopening
                  ? <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Reabrindo…</>
                  : <><RotateCcw className="w-3.5 h-3.5" /> Reabrir</>}
              </button>
            )}
          </div>
        </div>

        {loading && <div className="text-[12px] text-gray-500">Carregando…</div>}
        {error && (
          <div className="rounded-lg border border-red-200 dark:border-red-900 bg-red-50 dark:bg-red-900/20 p-4 text-[13px] text-red-700 dark:text-red-300">
            {error}
          </div>
        )}
        {syncToast && (
          <div
            role="status"
            data-testid="snapshot-sync-toast"
            className={`rounded-lg px-3 py-2 text-[12px] border ${
              syncToast.tone === 'success'
                ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300'
                : syncToast.tone === 'error'
                  ? 'border-red-500/40 bg-red-500/10 text-red-700 dark:text-red-300'
                  : 'border-gray-300 dark:border-gray-700 bg-gray-50 dark:bg-gray-800/40 text-gray-700 dark:text-gray-300'
            }`}
          >
            {syncToast.text}
          </div>
        )}

        {snap && !loading && (
          <>
            {/* ── 1. Spec 62 — MoM anomaly detection (topo do detail) ── */}
            <MoMDeltaBlock
              snapshotId={snap.id}
              isReadOnly={!isPending}
              onResolved={refreshPendencies}
            />

            {/* ── 2. Pendency panel (Spec 47 — single source of truth) ── */}
            {isPending && (
              <PendencyPanel
                snapshotId={snap.id}
                pendencies={pendencies}
                assetById={assetById}
                pendingTotal={pendingTotal}
                totalAssetsCount={totalAssetsCount}
                resolvedAssets={resolvedAssets}
                periodEndDate={snap.period_end_date}
                onResolved={refreshPendencies}
                onConfirm={handleConfirm}
                confirming={confirming}
                onEditPendency={(p) => {
                  const it = items.find(i => i.asset_id === p.asset_id)
                  if (it) setEditingItem(it)
                }}
              />
            )}

            {/* ── 3. KPI grid (prototype line 7167) ──────────────────── */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <KpiTile
                label="Patrimônio fim do mês"
                value={fmtBRL(totalBRL)}
                sub={`${fmtUSD(totalUSD, { compact: true })}${fxRate ? ` · PTAX ${fxRate.toFixed(4)}` : ''}`}
              />
              <KpiTile
                label="Variação MoM"
                value={
                  momDelta == null
                    ? '—'
                    : `${momDelta >= 0 ? '+' : ''}${(momDelta * 100).toFixed(2)}%`
                }
                intent={momDelta == null ? undefined : momDelta >= 0 ? 'positive' : 'negative'}
                sub={
                  momDeltaBRL == null
                    ? 'primeiro fechamento'
                    : momDeltaUSD == null
                      ? `${momDeltaBRL >= 0 ? '+' : ''}${fmtBRL(momDeltaBRL, { compact: true })}`
                      : `${momDeltaBRL >= 0 ? '+' : ''}${fmtBRL(momDeltaBRL, { compact: true })} · ${momDeltaUSD >= 0 ? '+' : ''}${fmtUSD(momDeltaUSD, { compact: true })}`
                }
              />
              <KpiTile
                label="Proventos recebidos"
                value={fmtBRL(proventosBRL, { compact: true })}
                sub={
                  fxRate
                    ? `${fmtUSD(proventosBRL / fxRate, { compact: true })} · ${proventosCount} evento${proventosCount === 1 ? '' : 's'}`
                    : `${proventosCount} evento${proventosCount === 1 ? '' : 's'}`
                }
              />
              <KpiTile
                label="Yield on portfolio"
                value={`${(yieldPct * 100).toFixed(2)}%`}
                sub="proventos / patrimônio fim"
              />
            </div>

            {/* ── 4. Composição + Proventos do mês (prototype 7192) ─── */}
            <div className="grid grid-cols-12 gap-4">
              <Card className="col-span-12 lg:col-span-7">
                <SectionTitle>
                  Composição por classe · {fmtDateBR(snap.period_end_date)}
                </SectionTitle>
                <div className="space-y-2">
                  {Object.entries(byClass)
                    .sort(([, a], [, b]) => b - a)
                    .map(([k, v]) => {
                      const meta = KLASS[k as CollapsedClassCode]
                      if (!meta) return null
                      return (
                        <div key={k} className="flex items-center gap-3">
                          <span
                            className="w-1.5 h-1.5 rounded-full shrink-0"
                            style={{ background: meta.color }}
                          />
                          <span className="text-[12px] text-gray-700 dark:text-gray-300 w-28 shrink-0">
                            {meta.label}
                          </span>
                          <div className="flex-1">
                            <HBar value={v} max={totalBRL} color={meta.color} height={6} />
                          </div>
                          <span className="text-[11px] tnum text-gray-500 w-12 text-right">
                            {totalBRL > 0 ? ((v / totalBRL) * 100).toFixed(1) : '0.0'}%
                          </span>
                          <span className="text-[11px] tnum text-gray-700 dark:text-gray-300 w-20 text-right">
                            {fmtBRL(v, { compact: true })}
                          </span>
                        </div>
                      )
                    })}
                  {Object.keys(byClass).length === 0 && (
                    <div className="text-[12px] text-gray-500 italic py-4 text-center">
                      Sem posições neste snapshot
                    </div>
                  )}
                </div>
              </Card>

              <Card className="col-span-12 lg:col-span-5">
                <SectionTitle
                  action={
                    <span className="text-[10px] text-gray-500 uppercase">
                      {proventosCount} eventos
                    </span>
                  }
                >
                  Proventos do mês
                </SectionTitle>
                {proventosCount === 0 ? (
                  <div className="text-[12px] text-gray-500 italic py-4 text-center">
                    Sem proventos neste mês
                  </div>
                ) : (
                  <div className="space-y-2">
                    {Object.entries(proventosByType)
                      .sort(([, a], [, b]) => b - a)
                      .map(([type, v]) => {
                        const meta = TYPE_META[type] ?? { label: type, color: '#94a3b8' }
                        return (
                          <div key={type} className="flex items-center gap-3">
                            <span
                              className="w-1.5 h-1.5 rounded-full"
                              style={{ background: meta.color }}
                            />
                            <span className="text-[12px] text-gray-700 dark:text-gray-300 flex-1">
                              {meta.label}
                            </span>
                            <span className="text-[11px] tnum text-gray-500">
                              {proventosBRL > 0 ? ((v / proventosBRL) * 100).toFixed(0) : '0'}%
                            </span>
                            <span className="text-[12px] tnum font-medium text-amber-700 dark:text-amber-300 w-20 text-right">
                              {fmtBRL(v, { compact: true })}
                            </span>
                          </div>
                        )
                      })}
                  </div>
                )}
              </Card>
            </div>

            {/* ── 4b. Eventos do mês (Spec 45) ────────────────────────── */}
            {proventosCount > 0 && (
              <Card padding="p-3">
                <div className="px-2 pt-2 pb-3 flex items-center justify-between gap-3 flex-wrap">
                  <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-500">
                    Eventos do mês · {filteredEventRows.length === proventosCount
                      ? `${proventosCount} provento${proventosCount === 1 ? '' : 's'}`
                      : `${filteredEventRows.length} de ${proventosCount}`}
                  </h3>
                  <button
                    onClick={() => exportEventosCsv()}
                    title="Exportar proventos do mês em CSV"
                    className="h-7 px-2 inline-flex items-center gap-1 rounded-md text-[11px] bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700"
                    data-testid="eventos-csv"
                  >
                    <Download className="w-3 h-3" /> CSV
                  </button>
                </div>
                <div className="px-2 pb-3 flex items-center gap-3 flex-wrap">
                  <div className="w-full max-w-xs">
                    <SearchInput
                      value={eventsSearch}
                      onChange={setEventsSearch}
                      placeholder="Buscar por ativo ou tipo…"
                    />
                  </div>
                  <MultiChips
                    options={[
                      { id: 'DIVIDEND', label: 'Dividendo', color: '#22c55e' },
                      { id: 'JCP', label: 'JCP', color: '#f59e0b' },
                      { id: 'INTEREST', label: 'Juros / Cupom', color: '#3b82f6' },
                      { id: 'SECURITIES_LENDING', label: 'Aluguel', color: '#8b5cf6' },
                      { id: 'OPTION_PREMIUM', label: 'Prêmio sintético', color: '#a855f7' },
                    ]}
                    selected={eventsTypeSel}
                    onChange={setEventsTypeSel}
                  />
                </div>
                <div className="overflow-x-auto -mx-1">
                  <table className="w-full text-[12px]" data-testid="distributions-table">
                    <thead>
                      <tr className="text-[10px] uppercase tracking-wider text-gray-500">
                        <SortHeader label="Data" col="event_date" sort={eventsSort} onToggle={toggleEventsSort} />
                        <SortHeader label="Ativo" col="label_primary" sort={eventsSort} onToggle={toggleEventsSort} />
                        <SortHeader label="Tipo" col="type" sort={eventsSort} onToggle={toggleEventsSort} />
                        <SortHeader label="Bruto (BRL)" col="gross_brl" sort={eventsSort} onToggle={toggleEventsSort} align="right" />
                        <th className="text-right font-medium px-3 py-2">Bruto (USD)</th>
                        <th className="text-right font-medium px-3 py-2">IRRF</th>
                        <SortHeader label="Líquido" col="net_native" sort={eventsSort} onToggle={toggleEventsSort} align="right" />
                      </tr>
                    </thead>
                    <tbody>
                      {filteredEventRows.map(r => {
                        const meta = TYPE_META[r.type] ?? { label: r.type, color: '#94a3b8' }
                        // Sintéticos (id começa com 'synthetic:') vêm de
                        // AssetMovement — não editáveis aqui; clique vira no-op.
                        const isSynthetic = r.id.startsWith('synthetic:')
                        const realDist = !isSynthetic
                          ? distributions.find(d => d.id === r.id)
                          : null
                        return (
                          <tr
                            key={r.id}
                            onClick={realDist ? () => setEditingDistribution(realDist) : undefined}
                            title={isSynthetic
                              ? 'Prêmio sintético derivado de movement — edite o lançamento de SELL_OPEN'
                              : 'Clique pra editar'}
                            className={`border-t border-gray-100 dark:border-gray-800 transition-colors ${
                              realDist
                                ? 'hover:bg-gray-50 dark:hover:bg-gray-800/30 cursor-pointer'
                                : 'hover:bg-gray-50/40 dark:hover:bg-gray-800/10 cursor-default'
                            }`}
                          >
                            <td className="px-3 py-2 tnum text-gray-500">
                              {fmtDateBR(r.event_date).slice(0, 5)}
                            </td>
                            <td className="px-3">
                              <div className="font-mono font-medium text-[12px]">
                                {r.label_primary}
                              </div>
                              {r.label_secondary && (
                                <div className="text-[10px] text-gray-500 truncate max-w-[200px]">
                                  {r.label_secondary}
                                </div>
                              )}
                            </td>
                            <td className="px-3">
                              <div className="inline-flex items-center gap-1.5 text-[11px]">
                                <span
                                  className="w-1.5 h-1.5 rounded-full"
                                  style={{ background: meta.color }}
                                />
                                <span className="text-gray-700 dark:text-gray-300">{meta.label}</span>
                              </div>
                            </td>
                            <td className="px-3 text-right tnum text-gray-500">
                              {r.gross_brl > 0 ? fmtBRL(r.gross_brl) : '—'}
                            </td>
                            <td className="px-3 text-right tnum text-gray-500">
                              {r.gross_usd > 0 ? fmtUSD(r.gross_usd) : '—'}
                            </td>
                            <td className="px-3 text-right tnum text-gray-500">
                              {r.tax_native != null && r.tax_native > 0 ? fmtMoney(r.tax_native, r.currency) : '—'}
                            </td>
                            <td className="px-3 text-right tnum font-medium text-emerald-700 dark:text-emerald-300">
                              {fmtMoney(r.net_native, r.currency)}
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              </Card>
            )}

            {/* ── 5. Top movers (prototype 7250) ───────────────────────── */}
            <div className="grid grid-cols-12 gap-4" data-testid="movers-row">
              <Card className="col-span-12 md:col-span-6">
                <SectionTitle>
                  Maiores altas{prevYm ? ` · vs ${ymLabelShort(prevYm)}` : ' · MoM'}
                </SectionTitle>
                {topUp.length === 0 ? (
                  <div className="text-[12px] text-gray-500 italic py-4 text-center">
                    {prevSnap ? 'Sem deltas significativos' : 'Sem snapshot anterior'}
                  </div>
                ) : (
                  <div className="space-y-2">
                    {topUp.map(m => (
                      <Link
                        key={m.asset.id}
                        to={`/assets/${m.asset.id}`}
                        className="flex items-center gap-3 p-2 -mx-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800/40"
                      >
                        <div
                          className="w-1 h-6 rounded-full"
                          style={{ background: KLASS[collapsedOf(m.asset.asset_class)]?.color || '#9ca3af' }}
                        />
                        <span className="font-mono text-[12px] font-medium flex-1">
                          {m.asset.ticker || m.asset.name}
                        </span>
                        <span className="text-[11px] text-gray-500 tnum w-20 text-right">
                          {fmtBRL(m.valueBRL, { compact: true })}
                        </span>
                        <span className="text-[12px] tnum text-emerald-500 dark:text-emerald-400 w-16 text-right">
                          +{(m.pct * 100).toFixed(2)}%
                        </span>
                      </Link>
                    ))}
                  </div>
                )}
              </Card>
              <Card className="col-span-12 md:col-span-6">
                <SectionTitle>
                  Maiores quedas{prevYm ? ` · vs ${ymLabelShort(prevYm)}` : ' · MoM'}
                </SectionTitle>
                {topDown.length === 0 ? (
                  <div className="text-[12px] text-gray-500 italic py-4 text-center">
                    {prevSnap ? 'Sem deltas significativos' : 'Sem snapshot anterior'}
                  </div>
                ) : (
                  <div className="space-y-2">
                    {topDown.map(m => (
                      <Link
                        key={m.asset.id}
                        to={`/assets/${m.asset.id}`}
                        className="flex items-center gap-3 p-2 -mx-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800/40"
                      >
                        <div
                          className="w-1 h-6 rounded-full"
                          style={{ background: KLASS[collapsedOf(m.asset.asset_class)]?.color || '#9ca3af' }}
                        />
                        <span className="font-mono text-[12px] font-medium flex-1">
                          {m.asset.ticker || m.asset.name}
                        </span>
                        <span className="text-[11px] text-gray-500 tnum w-20 text-right">
                          {fmtBRL(m.valueBRL, { compact: true })}
                        </span>
                        <span className="text-[12px] tnum text-red-500 dark:text-red-400 w-16 text-right">
                          {(m.pct * 100).toFixed(2)}%
                        </span>
                      </Link>
                    ))}
                  </div>
                )}
              </Card>
            </div>

            {/* ── 6. Origem dos dados (prototype 7282) ─────────────────── */}
            <Card>
              <SectionTitle>Origem dos dados deste fechamento</SectionTitle>
              <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
                <SourceCard
                  label="API OK" value={sources.api_ok}
                  hint="brapi · finnhub · coinbase"
                  bg="bg-emerald-500/10" border="border-emerald-500/20"
                  text="text-emerald-700 dark:text-emerald-400"
                />
                <SourceCard
                  label="Manual OK" value={sources.manual_done}
                  hint="você confirmou"
                  bg="bg-indigo-500/10" border="border-indigo-500/20"
                  text="text-indigo-700 dark:text-indigo-400"
                />
                <SourceCard
                  label="API falhou" value={sources.api_failed}
                  hint="timeout / 5xx / stale"
                  bg="bg-red-500/10" border="border-red-500/20"
                  text="text-red-700 dark:text-red-400"
                />
                <SourceCard
                  label="Manual pendente" value={sources.manual_pending}
                  hint="imóvel · cripto · FGTS"
                  bg="bg-amber-500/10" border="border-amber-500/20"
                  text="text-amber-700 dark:text-amber-400"
                />
                <SourceCard
                  label="Upload pendente" value={sources.upload_pending}
                  hint="extrato / nota"
                  bg="bg-amber-500/10" border="border-amber-500/20"
                  text="text-amber-700 dark:text-amber-400"
                  title={
                    'Pendências com reason=UPLOAD_REQUIRED — o sistema marca '
                    + 'um ativo precisa de extrato/nota porque a fonte do preço '
                    + 'depende de upload manual (ex: fundo sem ticker público). '
                    + 'Conte = quantos ativos esperam upload. Não é "esperado N '
                    + 'arquivos"; é "N ativos esperam algum arquivo".'
                  }
                />
              </div>
            </Card>

            {/* ── 7. Posições congeladas (prototype 7314) ────────────── */}
            <AssetFilterBar
              search={posSearch} onSearchChange={setPosSearch}
              klassSel={posKlassSel} onKlassChange={setPosKlassSel}
              countrySel={posCountrySel} onCountryChange={setPosCountrySel}
              fiOpts={posFiOpts} fiSel={posFiSel} onFiChange={setPosFiSel}
              includeZeroed={posIncludeNoValue} onIncludeZeroedChange={setPosIncludeNoValue}
              includeZeroedLabel="Incluir sem valor"
            />

            <Card padding="p-3">
              <div className="px-2 pt-2 pb-3 flex items-center justify-between">
                <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-500">
                  Posições congeladas · {filteredPositions.length === items.length
                    ? `${items.length} ativos`
                    : `${filteredPositions.length} de ${items.length} ativos`}
                </h3>
                <button
                  onClick={() => exportPositionsCsv()}
                  title="Exportar posições congeladas em CSV"
                  className="h-7 px-2 inline-flex items-center gap-1 rounded-md text-[11px] bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700"
                  data-testid="positions-csv"
                >
                  <Download className="w-3 h-3" /> CSV
                </button>
              </div>
              <div
                className={`overflow-x-auto -mx-1${
                  showAllPositions && filteredPositions.length > 20
                    ? ' max-h-[600px] overflow-y-auto'
                    : ''
                }`}
                data-testid="positions-wrapper"
              >
                <table className="w-full text-[12px]" data-testid="positions-table">
                  <thead>
                    <tr className="text-[10px] uppercase tracking-wider text-gray-500">
                      <th className="text-left font-medium px-3 py-2">Ativo</th>
                      <th className="text-left font-medium px-3 py-2">Classe</th>
                      <th className="text-left font-medium px-3 py-2">Custodiante</th>
                      <th className="text-right font-medium px-3 py-2">Qtd</th>
                      <th className="text-right font-medium px-3 py-2">Preço unitário</th>
                      <th className="text-right font-medium px-3 py-2">Valor total (BRL)</th>
                      <th className="text-right font-medium px-3 py-2">Valor total (USD)</th>
                      <th className="text-right font-medium px-3 py-2">% portfólio</th>
                      <th className="px-2" />
                    </tr>
                  </thead>
                  <tbody>
                    {filteredPositions
                      .slice(0, showAllPositions ? filteredPositions.length : 20)
                      .map(it => {
                      const a = assetById.get(it.asset_id)
                      if (!a) return null
                      const klass = collapsedOf(a.asset_class)
                      const hasValue = it.market_value_brl != null && Number(it.market_value_brl) > 0
                      const valueBRL = hasValue ? Number(it.market_value_brl) : 0
                      const valueUSD = it.market_value_usd != null
                        ? Number(it.market_value_usd)
                        : (hasValue && fxRate && fxRate > 0 ? valueBRL / fxRate : null)
                      const pct = totalBRL > 0 ? (valueBRL / totalBRL) * 100 : 0
                      const closePrice = it.unit_price != null ? Number(it.unit_price) : null
                      return (
                        <tr
                          key={it.asset_id}
                          onClick={() => {
                            // Spec 49 hotfix #10 — IN_REVIEW: open inline
                            // editor (so user can fix wrong values without
                            // leaving the fechamento). CLOSED: navigate to
                            // asset detail (snapshot is frozen).
                            if (isPending) {
                              setEditingItem(it)
                              return
                            }
                            const safeYm = ym ?? snap?.period_end_date.slice(0, 7) ?? ''
                            const mm = safeYm.split('-')[1]
                            const yyyy = safeYm.split('-')[0]
                            const label = mm && yyyy
                              ? `${MONTH_NAMES_LONG[parseInt(mm, 10) - 1]} ${yyyy}`
                              : 'Fechamento'
                            navigate(
                              `/assets/${a.id}`,
                              { state: { from: `/snapshots/${safeYm}`, fromLabel: label } },
                            )
                          }}
                          className="border-t border-gray-100 dark:border-gray-800 hover:bg-gray-50 dark:hover:bg-gray-800/30 transition-colors cursor-pointer"
                        >
                          <td className="px-3 py-2">
                            <div className="flex items-center gap-2">
                              <span
                                className="w-1 h-5 rounded-full"
                                style={{ background: KLASS[klass]?.color || '#9ca3af' }}
                              />
                              <div>
                                <div className="font-mono font-medium">
                                  {a.ticker || a.name}
                                </div>
                                <div className="text-[10px] text-gray-500 truncate max-w-[180px]">
                                  {a.name}
                                </div>
                              </div>
                            </div>
                          </td>
                          <td className="px-3"><ClassBadge klass={klass} size="xs" withDot={false} /></td>
                          <td className="px-3">
                            {(() => {
                              const fi = fiById.get(a.financial_institution_id)
                              const shortName = fi?.short_name ?? a.financial_institution_name
                              return (
                                <div className="flex items-center gap-1.5">
                                  <FILogo slug={fi?.logo_slug ?? null} shortName={shortName} size="sm" />
                                  <span className="text-[12px] text-gray-700 dark:text-gray-300 truncate max-w-[120px]">{shortName}</span>
                                </div>
                              )
                            })()}
                          </td>
                          <td className="px-3 text-right tnum text-gray-700 dark:text-gray-300">
                            {Number(it.quantity).toLocaleString('pt-BR', { maximumFractionDigits: 4 })}
                          </td>
                          <td className="px-3 text-right tnum text-gray-500">
                            {closePrice == null
                              ? '—'
                              : a.currency === 'USD'
                                ? `$ ${closePrice.toFixed(2)}`
                                : `R$ ${closePrice.toFixed(2)}`}
                          </td>
                          <td className="px-3 text-right tnum font-medium">
                            {hasValue ? fmtBRL(valueBRL) : <span className="text-gray-500">—</span>}
                          </td>
                          <td className="px-3 text-right tnum text-gray-500">
                            {valueUSD != null && valueUSD > 0 ? fmtUSD(valueUSD) : '—'}
                          </td>
                          <td className="px-3 text-right tnum text-gray-500">
                            {hasValue ? `${pct.toFixed(2)}%` : '—'}
                          </td>
                          <td className="px-3 text-gray-400">
                            <ChevronRight className="w-4 h-4" />
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
                {filteredPositions.length > 20 && !showAllPositions && (
                  <div className="px-3 py-2 text-[11px] text-gray-500 text-center">
                    + {filteredPositions.length - 20} ativos ·{' '}
                    <button
                      onClick={() => setShowAllPositions(true)}
                      className="text-indigo-500 dark:text-indigo-400 hover:underline"
                      data-testid="show-all-positions"
                    >
                      ver todos
                    </button>
                  </div>
                )}
              </div>
            </Card>

            {/* Spec 51 Bloco 3 — divergências aceitas (audit trail). */}
            <SnapshotDriftPanel drift={drift} />
          </>
        )}
      </div>
      {editingItem && snap && (() => {
        const a = assetById.get(editingItem.asset_id)
        if (!a) return null
        return (
          <SnapshotItemEditModal
            snapshotId={snap.id}
            ym={ym ?? snap.period_end_date.slice(0, 7)}
            item={editingItem}
            asset={a}
            fxRate={snap.fx_rate_usd_brl != null ? Number(snap.fx_rate_usd_brl) : null}
            onSaved={async (updated) => {
              setEditingItem(null)
              // Replace the matching item in state so the table reflects
              // the new values without a full refetch round-trip.
              setItems(prev => prev.map(it =>
                it.asset_id === updated.asset_id ? updated : it,
              ))
              await refreshPendencies()
            }}
            onDeleted={async (deletedAssetId) => {
              setEditingItem(null)
              setItems(prev => prev.filter(it => it.asset_id !== deletedAssetId))
              await refreshPendencies()
            }}
            onClose={() => setEditingItem(null)}
          />
        )
      })()}
      {editingDistribution && (
        <DistributionEditModal
          distribution={editingDistribution}
          onSaved={(updated) => {
            setEditingDistribution(null)
            setDistributions(prev => prev.map(d => d.id === updated.id ? updated : d))
          }}
          onDeleted={(deletedId) => {
            setEditingDistribution(null)
            setDistributions(prev => prev.filter(d => d.id !== deletedId))
          }}
          onClose={() => setEditingDistribution(null)}
        />
      )}
      {addAssetOpen && snap && (
        <AddSnapshotAssetModal
          snapshotId={snap.id}
          existingAssetIds={new Set(items.map(it => it.asset_id))}
          assets={assets}
          onAdded={async (newItem) => {
            setAddAssetOpen(false)
            setItems(prev => [...prev, newItem])
            await refreshPendencies()
          }}
          onClose={() => setAddAssetOpen(false)}
        />
      )}
    </AppLayout>
  )
}


// ── Sub-components ──────────────────────────────────────────────────────────

const TYPE_META: Record<string, { label: string; color: string }> = {
  DIVIDEND:           { label: 'Dividendo',     color: '#22c55e' },
  JCP:                { label: 'JCP',           color: '#f59e0b' },
  INTEREST:           { label: 'Juros / Cupom', color: '#3b82f6' },
  SECURITIES_LENDING: { label: 'Aluguel',       color: '#8b5cf6' },
  OPTION_PREMIUM:     { label: 'Prêmio sintético', color: '#a855f7' },
}

function KpiTile({
  label, value, sub, intent,
}: { label: string; value: string; sub?: string; intent?: 'positive' | 'negative' }) {
  const intentColor =
    intent === 'negative' ? 'text-red-500 dark:text-red-400'
    : intent === 'positive' ? 'text-emerald-500 dark:text-emerald-400'
    : ''
  return (
    <div className="px-4 py-3 rounded-xl bg-gray-50 dark:bg-gray-800/40 border border-gray-200 dark:border-gray-800">
      <div className="text-[10px] uppercase tracking-wider font-medium text-gray-500">{label}</div>
      <div className={`mt-1 text-lg font-semibold tnum ${intentColor}`}>{value}</div>
      {sub && <div className="text-[11px] text-gray-500 mt-0.5">{sub}</div>}
    </div>
  )
}

function SortHeader<K extends string>({
  label, col, sort, onToggle, align = 'left',
}: {
  label: string; col: K; sort: { key: K; dir: 'asc' | 'desc' };
  onToggle: (key: K) => void; align?: 'left' | 'right';
}) {
  const active = sort.key === col
  const arrow = active ? (sort.dir === 'asc' ? '↑' : '↓') : ''
  return (
    <th
      onClick={() => onToggle(col)}
      className={`font-medium px-3 py-2 cursor-pointer select-none hover:text-gray-700 dark:hover:text-gray-300 ${
        align === 'right' ? 'text-right' : 'text-left'
      } ${active ? 'text-gray-700 dark:text-gray-300' : ''}`}
    >
      {label}{active ? ` ${arrow}` : ''}
    </th>
  )
}

function SourceCard({
  label, value, hint, bg, border, text, title,
}: {
  label: string; value: number; hint: string;
  bg: string; border: string; text: string;
  title?: string;
}) {
  return (
    <div className={`px-3 py-3 rounded-lg ${bg} border ${border}`} title={title}>
      <div className={`text-[10px] uppercase tracking-wider font-semibold ${text}`}>
        {label}
      </div>
      <div className={`text-xl font-semibold tnum mt-1 ${text}`}>{value}</div>
      <div className="text-[10px] text-gray-500 mt-1">{hint}</div>
    </div>
  )
}

