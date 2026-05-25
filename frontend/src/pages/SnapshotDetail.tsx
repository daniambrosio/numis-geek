/* Spec 35 — /snapshots/{ym}: frozen monthly report + pendency review. */
import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { ArrowLeft, RotateCcw } from 'lucide-react'

import {
  api,
  type AssetOut,
  type SnapshotItemOut,
  type SnapshotOut,
  type SnapshotPendencyOut,
  type UserOut,
} from '../lib/api'
import AppLayout from '../components/AppLayout'
import PendencyPanel from '../components/PendencyPanel'
import SourceMixBar from '../components/SourceMixBar'
import StatusPill from '../components/StatusPill'
import { Card, PageHeader } from '../components/ui'

const MONTH_NAMES = [
  'Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho',
  'Julho', 'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro',
]

function fmtBRL(n: number, opts: { compact?: boolean } = {}) {
  return n.toLocaleString('pt-BR', {
    style: 'currency', currency: 'BRL',
    notation: opts.compact ? 'compact' : 'standard',
    maximumFractionDigits: opts.compact ? 1 : 0,
  })
}

function ymLabel(ym: string): string {
  const [y, m] = ym.split('-')
  return `${MONTH_NAMES[parseInt(m, 10) - 1]} ${y}`
}

export default function SnapshotDetail() {
  const { ym } = useParams<{ ym: string }>()
  const navigate = useNavigate()
  const [me, setMe] = useState<UserOut | null>(null)
  const [snap, setSnap] = useState<SnapshotOut | null>(null)
  const [items, setItems] = useState<SnapshotItemOut[]>([])
  const [pendencies, setPendencies] = useState<SnapshotPendencyOut[]>([])
  const [assets, setAssets] = useState<AssetOut[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [allSnaps, setAllSnaps] = useState<SnapshotOut[]>([])

  useEffect(() => {
    api.me().then(setMe).catch(() => navigate('/login'))
  }, [navigate])

  useEffect(() => {
    if (!me || !ym) return
    let cancelled = false
    setLoading(true)
    setError('')

    api.listSnapshots()
      .then(async list => {
        if (cancelled) return
        setAllSnaps(list)
        const match = list.find(s => s.period_end_date.startsWith(ym))
        if (!match) {
          setError(`Sem snapshot para ${ym}.`)
          setLoading(false)
          return
        }
        setSnap(match)
        const [its, pens, as] = await Promise.all([
          api.listSnapshotItems(match.id),
          api.listSnapshotPendencies(match.id),
          api.listAssets({ include_inactive: true }),
        ])
        if (cancelled) return
        setItems(its)
        setPendencies(pens)
        setAssets(as)
      })
      .catch(e => setError(e instanceof Error ? e.message : 'Erro'))
      .finally(() => { if (!cancelled) setLoading(false) })

    return () => { cancelled = true }
  }, [me, ym])

  const assetById = useMemo(() => {
    const m = new Map<string, AssetOut>()
    for (const a of assets) m.set(a.id, a)
    return m
  }, [assets])

  async function refreshPendencies() {
    if (!snap) return
    const pens = await api.listSnapshotPendencies(snap.id)
    setPendencies(pens)
    const fresh = await api.listSnapshots()
    setAllSnaps(fresh)
    setSnap(fresh.find(s => s.id === snap.id) ?? snap)
  }

  async function handleConfirm() {
    if (!snap) return
    try {
      const updated = await api.confirmSnapshot(snap.id)
      setSnap(updated)
    } catch (e) {
      alert(e instanceof Error ? e.message : 'Erro')
    }
  }

  async function handleReopen() {
    if (!snap) return
    const reason = window.prompt('Motivo da reabertura:')
    if (!reason) return
    try {
      const updated = await api.reopenSnapshot(snap.id, reason)
      setSnap(updated)
      const pens = await api.listSnapshotPendencies(snap.id)
      setPendencies(pens)
    } catch (e) {
      alert(e instanceof Error ? e.message : 'Erro')
    }
  }

  // Compute source mix for the audit card.
  const sourceMix = useMemo(() => {
    let api_ok = 0, manual_ok = 0, api_fail = 0, manual_pend = 0, upload_pend = 0
    const openByAsset = new Map<string, SnapshotPendencyOut>()
    for (const p of pendencies) {
      if (!p.resolved_at) openByAsset.set(p.asset_id, p)
    }
    for (const it of items) {
      const a = assetById.get(it.asset_id)
      if (!a) continue
      const pen = openByAsset.get(it.asset_id)
      if (pen) {
        if (pen.reason === 'API_FAILED' || pen.reason === 'STALE_PRICE') api_fail++
        else if (pen.reason === 'UPLOAD_REQUIRED') upload_pend++
        else manual_pend++
      } else if (a.price_source === 'MANUAL' || a.price_source == null) {
        manual_ok++
      } else {
        api_ok++
      }
    }
    return [
      { label: 'API ok',         count: api_ok,      color: '#22c55e' },
      { label: 'Manual ok',      count: manual_ok,   color: '#3b82f6' },
      { label: 'API falhou',     count: api_fail,    color: '#ef4444' },
      { label: 'Manual pend.',   count: manual_pend, color: '#f59e0b' },
      { label: 'Upload pend.',   count: upload_pend, color: '#a855f7' },
    ]
  }, [items, pendencies, assetById])

  // Prev/next by period_end ordering.
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

  if (!me) return null

  return (
    <AppLayout user={me}>
      <div className="space-y-6">
        <PageHeader
          title={snap ? `Fechamento · ${ymLabel(ym ?? '')}` : 'Fechamento'}
          action={
            <div className="flex items-center gap-2">
              <Link
                to="/snapshots"
                className="h-8 px-3 inline-flex items-center gap-1.5 rounded-lg text-[12px] bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700"
              >
                <ArrowLeft className="w-3.5 h-3.5" /> Lista
              </Link>
              {snap?.status === 'CLOSED' && (
                <button
                  onClick={handleReopen}
                  className="h-8 px-3 inline-flex items-center gap-1.5 rounded-lg text-[12px] border border-amber-300 dark:border-amber-700 text-amber-700 dark:text-amber-400 hover:bg-amber-50 dark:hover:bg-amber-900/20"
                >
                  <RotateCcw className="w-3.5 h-3.5" /> Reabrir
                </button>
              )}
            </div>
          }
        />

        {loading && (
          <div className="text-[12px] text-gray-500">Carregando…</div>
        )}
        {error && (
          <div className="rounded-lg border border-red-200 dark:border-red-900 bg-red-50 dark:bg-red-900/20 p-4 text-[13px] text-red-700 dark:text-red-300">
            {error}
          </div>
        )}

        {snap && !loading && (
          <>
            {/* Header card */}
            <Card>
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-[10px] uppercase tracking-wider text-gray-500 font-semibold">
                  Período {snap.period_end_date}
                </span>
                <StatusPill status={snap.status} />
                <span className="text-[10px] uppercase tracking-wider text-gray-500">
                  {snap.source}
                </span>
                {snap.closed_at && (
                  <span className="text-[10px] text-gray-500">
                    fechado em {new Date(snap.closed_at).toLocaleString('pt-BR')}
                  </span>
                )}
                <div className="flex-1" />
                {prevSnap && (
                  <Link
                    to={`/snapshots/${prevSnap.period_end_date.slice(0, 7)}`}
                    className="text-[11px] text-indigo-500 hover:underline"
                  >
                    ← {prevSnap.period_end_date.slice(0, 7)}
                  </Link>
                )}
                {nextSnap && (
                  <Link
                    to={`/snapshots/${nextSnap.period_end_date.slice(0, 7)}`}
                    className="text-[11px] text-indigo-500 hover:underline"
                  >
                    {nextSnap.period_end_date.slice(0, 7)} →
                  </Link>
                )}
              </div>

              <div className="mt-3 grid grid-cols-2 lg:grid-cols-4 gap-3">
                <KpiTile
                  label="Patrimônio"
                  value={fmtBRL(Number(snap.total_value_brl), { compact: true })}
                  sub={snap.total_value_usd ? `${Number(snap.total_value_usd).toLocaleString('pt-BR', { style: 'currency', currency: 'USD', notation: 'compact', maximumFractionDigits: 1 })}` : undefined}
                />
                <KpiTile label="PTAX USD/BRL" value={snap.fx_rate_usd_brl ? Number(snap.fx_rate_usd_brl).toFixed(4) : '—'} />
                <KpiTile label="Itens" value={String(snap.items_count)} />
                <KpiTile
                  label="Pendências"
                  value={`${snap.pendencies_open}/${snap.pendencies_total}`}
                  sub={snap.pendencies_open === 0 ? 'tudo resolvido' : 'aguardando'}
                />
              </div>
            </Card>

            {/* Pendency panel (only when IN_REVIEW) */}
            {snap.status === 'IN_REVIEW' && (
              <PendencyPanel
                pendencies={pendencies}
                onResolved={refreshPendencies}
                onConfirm={handleConfirm}
              />
            )}

            {/* Source audit */}
            <Card>
              <div className="text-[10px] uppercase tracking-wider text-gray-500 font-semibold mb-2">
                Auditoria de fontes
              </div>
              <SourceMixBar slices={sourceMix} />
            </Card>

            {/* Frozen positions */}
            <Card padding="p-3">
              <div className="text-[10px] uppercase tracking-wider text-gray-500 font-semibold mb-2 px-2">
                Posições congeladas
              </div>
              <div className="overflow-x-auto -mx-1">
                <table className="w-full text-[12px]">
                  <thead>
                    <tr className="text-[10px] uppercase tracking-wider text-gray-500">
                      <th className="text-left font-medium px-2 py-2">Ativo</th>
                      <th className="text-right font-medium px-2 py-2">Qtd</th>
                      <th className="text-right font-medium px-2 py-2">Preço</th>
                      <th className="text-right font-medium px-2 py-2">Valor BRL</th>
                    </tr>
                  </thead>
                  <tbody>
                    {items
                      .slice()
                      .sort((a, b) => Number(b.market_value_brl ?? 0) - Number(a.market_value_brl ?? 0))
                      .map(it => {
                        const a = assetById.get(it.asset_id)
                        return (
                          <tr
                            key={it.asset_id}
                            className="border-t border-gray-100 dark:border-gray-800 hover:bg-gray-50 dark:hover:bg-gray-800/30 transition-colors"
                          >
                            <td className="px-2 py-2">
                              {a ? (
                                <Link to={`/assets/${a.id}`} className="font-mono font-medium hover:text-indigo-500">
                                  {a.ticker ?? a.name}
                                </Link>
                              ) : it.asset_id.slice(0, 8)}
                              {a && (
                                <div className="text-[10px] text-gray-500 truncate max-w-[260px]">{a.name}</div>
                              )}
                            </td>
                            <td className="px-2 text-right tnum">{Number(it.quantity).toLocaleString('pt-BR', { maximumFractionDigits: 4 })}</td>
                            <td className="px-2 text-right tnum text-gray-500">
                              {it.unit_price != null ? Number(it.unit_price).toLocaleString('pt-BR', { maximumFractionDigits: 2 }) : '—'}
                            </td>
                            <td className="px-2 text-right tnum font-medium">
                              {it.market_value_brl != null ? fmtBRL(Number(it.market_value_brl), { compact: true }) : '—'}
                            </td>
                          </tr>
                        )
                      })}
                  </tbody>
                </table>
              </div>
            </Card>
          </>
        )}
      </div>
    </AppLayout>
  )
}

function KpiTile({
  label, value, sub,
}: { label: string; value: string; sub?: string }) {
  return (
    <div className="px-4 py-3 rounded-xl bg-gray-50 dark:bg-gray-800/40 border border-gray-200 dark:border-gray-800">
      <div className="text-[10px] uppercase tracking-wider font-medium text-gray-500">{label}</div>
      <div className="mt-1 text-lg font-semibold tnum">{value}</div>
      {sub && <div className="text-[11px] text-gray-500 mt-0.5">{sub}</div>}
    </div>
  )
}
