import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import {
  api, type AssetOut, type FinancialInstitutionOut, type AssetMovementOut,
  type PortfolioOut, type PositionOut, type SnapshotOut, type UserOut,
} from '../lib/api'
import AppLayout from '../components/AppLayout'
import ProventosChart from '../components/ProventosChart'
import ProventosTypeList from '../components/ProventosTypeList'
import { useInReviewSnapshot } from '../lib/useInReviewSnapshot'
import { AlertTriangle } from 'lucide-react'
import { Card, SectionTitle, FILogo } from '../components/ui'
import { DonutChart, HBar } from '../components/charts'
import { KLASS, collapsedOf, fiTokenFor } from '../lib/tokens'

const OUTROS_COLOR = '#9ca3af'

function fmtBRL(n: number, opts: { compact?: boolean } = {}) {
  if (opts.compact && Math.abs(n) >= 1000) {
    return n.toLocaleString('pt-BR', {
      style: 'currency', currency: 'BRL', notation: 'compact', maximumFractionDigits: 1,
    })
  }
  return n.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })
}

function fmtUSD(n: number, opts: { compact?: boolean } = {}) {
  if (opts.compact && Math.abs(n) >= 1000) {
    return n.toLocaleString('en-US', {
      style: 'currency', currency: 'USD', notation: 'compact', maximumFractionDigits: 1,
    })
  }
  return n.toLocaleString('en-US', { style: 'currency', currency: 'USD' })
}

function fmtMoney(n: number, currency: string) {
  return n.toLocaleString('pt-BR', { style: 'currency', currency })
}

export default function Dashboard() {
  const navigate = useNavigate()
  const [me, setMe] = useState<UserOut | null>(null)
  const [assets, setAssets] = useState<AssetOut[]>([])
  const [institutions, setInstitutions] = useState<FinancialInstitutionOut[]>([])
  const [positions, setPositions] = useState<Map<string, PositionOut | null>>(new Map())
  const [recent, setRecent] = useState<AssetMovementOut[]>([])
  const [snapshots, setSnapshots] = useState<SnapshotOut[]>([])
  const [portfolio, setPortfolio] = useState<PortfolioOut | null>(null)
  // Spec 33 — local synthetic-on toggle for Dashboard Proventos card.
  // No UI toggle on Dashboard, so this stays at the default.
  const [syntheticOnDashboard, setSyntheticOnDashboard] = useState(true)

  useEffect(() => {
    api.me().then(setMe).catch(() => navigate('/login'))
  }, [navigate])

  useEffect(() => {
    if (!me) return
    api.listSnapshots().then(setSnapshots).catch(() => setSnapshots([]))
    api.getPortfolio().then(setPortfolio).catch(() => setPortfolio(null))
    Promise.all([
      api.listAssets({}),
      api.listFinancialInstitutions(),
      api.listAssetMovements({ page_size: 10 }),
    ])
      .then(([as, fis, lan]) => {
        setAssets(as)
        setInstitutions(fis)
        setRecent(lan.items)
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
      .catch(() => { /* leave dashboard empty on error */ })
  }, [me])

  const fiById = useMemo(() => {
    const m = new Map<string, FinancialInstitutionOut>()
    for (const fi of institutions) m.set(fi.id, fi)
    return m
  }, [institutions])

  // Live aggregation from positions — used for received + movers (per-asset
  // variation), and as a fallback when portfolio snapshot isn't loaded yet.
  const liveAgg = useMemo(() => {
    let invested = 0
    let current = 0
    let received = 0
    let loaded = 0
    const moversList: Array<{ asset: AssetOut; variation: number; pnl: number }> = []

    for (const a of assets) {
      const p = positions.get(a.id)
      if (p === undefined) continue
      loaded += 1
      if (!p) continue
      invested += Number(p.total_invested_brl ?? 0)
      received += Number(p.total_received_brl ?? 0)
      const inv = Number(p.total_invested_brl ?? 0)
      const cur = p.current_value_brl != null ? Number(p.current_value_brl) : inv
      current += cur
      if (p.variation != null) {
        moversList.push({
          asset: a,
          variation: Number(p.variation),
          pnl: Number(p.current_value_brl ?? 0) - inv,
        })
      }
    }
    moversList.sort((a, b) => Math.abs(b.variation) - Math.abs(a.variation))
    return {
      invested, current, received,
      movers: moversList.slice(0, 5),
      loading: loaded < assets.length,
    }
  }, [assets, positions])

  // Portfolio summary (snapshot-based) drives the hero numbers + breakdowns
  // — same source as the /portfolio page, so the two stay consistent.
  // Falls back to liveAgg when no snapshot exists.
  //
  // Note: Notion-imported snapshots have total_invested_brl=0 on the header
  // (the importer didn't populate it). When that happens, use the
  // positions-derived invested instead.
  const { totalInvested, totalCurrent, totalReceived, byClass, byFi, byCountry, movers, loading } = useMemo(() => {
    const hasPortfolio = !!portfolio && portfolio.source !== 'empty'
    const byClassArr = hasPortfolio
      ? portfolio!.by_class.map(c => ({ klass: collapsedOf(c.asset_class), value: c.value_brl })).sort((a, b) => b.value - a.value)
      : []
    const byFiArr = hasPortfolio
      ? portfolio!.by_custodian.map(c => ({ fi: c.fi_id, value: c.value_brl })).sort((a, b) => b.value - a.value)
      : []
    const byCountryArr = hasPortfolio
      ? portfolio!.by_country.map(c => ({ country: c.country, value: c.value_brl })).sort((a, b) => b.value - a.value)
      : []
    // Prefer snapshot's invested; fall back to live (positions) when snapshot
    // is missing the value or it's zero.
    const snapInvested = hasPortfolio ? portfolio!.total_invested_brl : 0
    const invested = snapInvested > 0 ? snapInvested : liveAgg.invested
    // Proventos: prefer portfolio's all-time received (sums Distribution
    // table directly, including distributions from now-inactive assets);
    // fall back to live positions otherwise. This is what makes Dashboard
    // and /distributions agree.
    const received = hasPortfolio ? portfolio!.total_received_brl : liveAgg.received
    return {
      totalInvested: invested,
      totalCurrent: hasPortfolio ? portfolio!.total_value_brl : liveAgg.current,
      totalReceived: received,
      byClass: byClassArr,
      byFi: byFiArr,
      byCountry: byCountryArr,
      movers: liveAgg.movers,
      loading: !portfolio && liveAgg.loading,
    }
  }, [portfolio, liveAgg])

  const ptaxRate = portfolio?.ptax_rate ?? null

  if (!me) return null

  const TOP_N = 5
  const topClasses = byClass.slice(0, TOP_N)
  const restClasses = byClass.slice(TOP_N)
  const outrosValue = restClasses.reduce((s, x) => s + x.value, 0)
  const donutData = [
    ...topClasses.map(c => ({ value: c.value, color: KLASS[c.klass].color, label: KLASS[c.klass].label })),
    ...(restClasses.length > 0 ? [{ value: outrosValue, color: OUTROS_COLOR, label: 'Outros' }] : []),
  ]

  const topFis = byFi.slice(0, 5)
  const outrosFis = byFi.slice(5)
  const outrosFisSum = outrosFis.reduce((s, x) => s + x.value, 0)
  const fiMax = topFis[0]?.value ?? 1

  return (
    <AppLayout user={me}>
      <div className="space-y-6">
        <SnapshotReviewBanner />
        {/* Hero */}
        <Card padding="p-0" className="overflow-hidden">
          <div className="grid grid-cols-12 gap-0">
            <div className="col-span-12 lg:col-span-7 p-6 lg:p-8">
              <div className="flex items-center gap-2">
                <div className="text-[11px] font-semibold uppercase tracking-wider text-gray-500 dark:text-gray-400">
                  Patrimônio investido
                </div>
                <span className="text-[11px] text-gray-500">·</span>
                <div className="text-[11px] text-gray-500 dark:text-gray-400">
                  {new Date().toLocaleDateString('pt-BR')}
                </div>
              </div>
              <div className="mt-2 flex items-baseline gap-3">
                <div className="text-4xl lg:text-5xl font-semibold tracking-tight tnum money text-gray-900 dark:text-white">
                  {loading && totalCurrent === 0 ? '…' : fmtBRL(totalCurrent)}
                </div>
              </div>
              {ptaxRate && (
                <div className="mt-1 flex items-baseline gap-2">
                  <div className="text-base text-gray-500 dark:text-gray-400 tnum money">
                    {fmtUSD(totalCurrent / ptaxRate)}
                  </div>
                  <span className="text-[11px] text-gray-500 dark:text-gray-400">
                    PTAX R$ {ptaxRate.toFixed(4)}
                  </span>
                </div>
              )}
              <div className="mt-1 text-[11px] text-gray-500 dark:text-gray-400">
                Patrimônio investido em valor de mercado · Caixa & Cartões chegam com spec futura
              </div>
              <div className="mt-5 grid grid-cols-3 gap-3">
                <Pill
                  label="Investido"
                  value={fmtBRL(totalInvested, { compact: true })}
                  usdValue={ptaxRate ? fmtUSD(totalInvested / ptaxRate, { compact: true }) : undefined}
                />
                <Pill
                  label="Ganho/perda"
                  value={`${totalCurrent - totalInvested >= 0 ? '+' : ''}${fmtBRL(totalCurrent - totalInvested, { compact: true })}`}
                  usdValue={ptaxRate
                    ? `${totalCurrent - totalInvested >= 0 ? '+' : ''}${fmtUSD((totalCurrent - totalInvested) / ptaxRate, { compact: true })}`
                    : undefined}
                  tone={totalCurrent - totalInvested >= 0 ? 'positive' : 'negative'}
                  money
                />
                <Pill
                  label="Proventos"
                  value={fmtBRL(totalReceived, { compact: true })}
                  usdValue={ptaxRate ? fmtUSD(totalReceived / ptaxRate, { compact: true }) : undefined}
                  tone={totalReceived > 0 ? 'positive' : undefined}
                  money
                />
              </div>
              <div className="mt-5 flex items-center gap-2">
                <span className="text-[11px] text-gray-500 dark:text-gray-400">
                  <span className="tnum money font-medium">{fmtBRL(totalReceived, { compact: true })}</span> em proventos acumulados
                  {totalReceived === 0 && <span className="ml-1 text-gray-400">— ativa após spec 08 (Distribution)</span>}
                </span>
              </div>
            </div>
            <div className="col-span-12 lg:col-span-5 p-6 lg:p-8 border-t lg:border-t-0 lg:border-l border-gray-200 dark:border-gray-800 bg-gradient-to-br from-indigo-500/5 to-transparent">
              <div className="flex items-center justify-between">
                <div className="text-[11px] font-semibold uppercase tracking-wider text-gray-500 dark:text-gray-400">
                  Evolução
                </div>
                <span className="text-[10px] text-gray-400 dark:text-gray-600">
                  {snapshots.length} {snapshots.length === 1 ? 'snapshot' : 'snapshots'}
                </span>
              </div>
              {snapshots.length === 0 ? (
                <div className="mt-6 rounded-xl border border-dashed border-gray-300 dark:border-gray-700 p-6 text-center">
                  <div className="text-[11px] text-gray-500 dark:text-gray-400">Sem snapshots ainda</div>
                  <div className="text-[10px] text-gray-400 dark:text-gray-600 mt-1">
                    Rode <code className="text-[10px]">snapshot create</code> ou POST /snapshots
                  </div>
                </div>
              ) : (
                <SnapshotSeries snapshots={snapshots} currentBrl={totalCurrent} />
              )}
            </div>
          </div>
        </Card>

        {/* Row 1 */}
        <div className="grid grid-cols-12 gap-6">
          <Card className="col-span-12 lg:col-span-5">
            <SectionTitle action={<span className="text-[11px] text-gray-500">{byClass.length} classes</span>}>
              Alocação por classe
            </SectionTitle>
            {byClass.length === 0 ? (
              <EmptyMini hint="Sem posições agregadas ainda." />
            ) : (
              <div className="flex items-center gap-6">
                <div className="relative shrink-0">
                  <DonutChart data={donutData} size={184} stroke={22} />
                  <div className="absolute inset-0 flex flex-col items-center justify-center">
                    <div className="text-[10px] uppercase tracking-wider text-gray-500 dark:text-gray-400">Total</div>
                    <div className="text-base font-semibold tnum money text-gray-900 dark:text-white">
                      {fmtBRL(totalCurrent, { compact: true })}
                    </div>
                  </div>
                </div>
                <div className="flex-1 space-y-1.5 min-w-0">
                  {donutData.map((d, i) => {
                    const pct = totalCurrent ? d.value / totalCurrent : 0
                    return (
                      <div key={i} className="flex items-center gap-2 text-[12px]">
                        <span className="w-2 h-2 rounded-sm shrink-0" style={{ background: d.color }} />
                        <span className="text-gray-700 dark:text-gray-300 truncate">{d.label}</span>
                        <div className="flex-1" />
                        <span className="tnum text-gray-500 dark:text-gray-400">{(pct * 100).toFixed(1)}%</span>
                        <span className="tnum money text-gray-400 w-20 text-right">{fmtBRL(d.value, { compact: true })}</span>
                      </div>
                    )
                  })}
                </div>
              </div>
            )}
          </Card>

          <Card className="col-span-12 lg:col-span-3">
            <SectionTitle>BR vs US</SectionTitle>
            {byCountry.length === 0 ? (
              <EmptyMini hint="Sem alocação por país ainda." />
            ) : (
              <div className="space-y-4">
                {byCountry.map(c => {
                  const pct = totalCurrent ? c.value / totalCurrent : 0
                  return (
                    <div key={c.country}>
                      <div className="flex items-center justify-between text-[12px] mb-1.5">
                        <div className="flex items-center gap-2">
                          <span className="text-base">{c.country === 'BR' ? '🇧🇷' : c.country === 'US' ? '🇺🇸' : '🌐'}</span>
                          <span className="font-medium text-gray-900 dark:text-white">
                            {c.country === 'BR' ? 'Brasil' : c.country === 'US' ? 'Estados Unidos' : c.country}
                          </span>
                        </div>
                        <span className="tnum text-gray-500 dark:text-gray-400">{(pct * 100).toFixed(1)}%</span>
                      </div>
                      <HBar value={c.value} max={byCountry[0].value} color={c.country === 'BR' ? '#22c55e' : '#3b82f6'} height={8} />
                      <div className="mt-1 text-[11px] text-gray-500 dark:text-gray-400 tnum money">
                        {fmtBRL(c.value, { compact: true })}
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </Card>

          <Card className="col-span-12 lg:col-span-4" padding="p-4">
            <SectionTitle action={
              <Link to="/distributions" className="text-[11px] text-indigo-500 dark:text-indigo-400 hover:opacity-80">
                Ver todos →
              </Link>
            }>
              Proventos · 12M
            </SectionTitle>
            <div className="-mt-1">
              <ProventosChart
                defaultBreakdown="klass"
                defaultCurrency="BRL"
                defaultPeriod="12m"
                includeSynthetic={syntheticOnDashboard}
                onIncludeSyntheticChange={setSyntheticOnDashboard}
                compact
                hideToggles
                noCard
              />
            </div>
            <ProventosTypeList
              includeSynthetic={syntheticOnDashboard}
              currency="BRL"
              period="12m"
            />
          </Card>
        </div>

        {/* Row 2 */}
        <div className="grid grid-cols-12 gap-6">
          <Card className="col-span-12 lg:col-span-7">
            <SectionTitle
              action={
                <Link to="/instituicoes" className="text-[11px] text-indigo-500 dark:text-indigo-400 hover:opacity-80">
                  Ver todos →
                </Link>
              }
            >
              Distribuição por custodiante
            </SectionTitle>
            {topFis.length === 0 ? (
              <EmptyMini hint="Sem dados de custodiantes ainda." />
            ) : (
              <div className="space-y-3">
                {topFis.map((f, i) => {
                  const fi = fiById.get(f.fi)
                  const pct = totalCurrent ? f.value / totalCurrent : 0
                  const color = fi ? fiTokenFor(fi.logo_slug, fi.short_name).color : '#94a3b8'
                  return (
                    <div
                      key={i}
                      className="flex items-center gap-3 p-2 -mx-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800/40 transition-colors"
                    >
                      <FILogo slug={fi?.logo_slug ?? null} shortName={fi?.short_name ?? '··'} size="md" />
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center justify-between">
                          <span className="text-sm font-medium text-gray-900 dark:text-white">{fi?.short_name ?? '—'}</span>
                          <span className="text-sm tnum money text-gray-900 dark:text-white">{fmtBRL(f.value, { compact: true })}</span>
                        </div>
                        <div className="mt-1 flex items-center gap-3">
                          <div className="flex-1"><HBar value={f.value} max={fiMax} color={color} height={4} /></div>
                          <span className="text-[11px] tnum text-gray-500 dark:text-gray-400 w-10 text-right">{(pct * 100).toFixed(1)}%</span>
                        </div>
                      </div>
                    </div>
                  )
                })}
                {outrosFis.length > 0 && (
                  <div className="flex items-center gap-3 p-2 -mx-2 text-gray-500 dark:text-gray-400">
                    <div className="w-8 h-8 rounded-md border border-dashed border-gray-300 dark:border-gray-700 flex items-center justify-center text-[10px]">
                      +{outrosFis.length}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center justify-between">
                        <span className="text-sm">Outros ({outrosFis.length} custodiantes)</span>
                        <span className="text-sm tnum money">{fmtBRL(outrosFisSum, { compact: true })}</span>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            )}
          </Card>

          <Card className="col-span-12 lg:col-span-5">
            <SectionTitle>Top movers</SectionTitle>
            {movers.length === 0 ? (
              <EmptyMini hint="Defina preço atual em ativos pra ver movimentação." />
            ) : (
              <div className="space-y-2">
                {movers.map(m => {
                  const klass = collapsedOf(m.asset.asset_class)
                  return (
                    <div key={m.asset.id} className="flex items-center gap-3 px-2 py-1.5 -mx-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800/40 transition-colors">
                      <span className="w-1.5 h-7 rounded-full shrink-0" style={{ background: KLASS[klass].color }} />
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <span className="font-mono text-[12px] font-medium text-gray-900 dark:text-white">
                            {m.asset.ticker || m.asset.name.slice(0, 18)}
                          </span>
                          <span className="text-[11px] leading-none">
                            {m.asset.country === 'BR' ? '🇧🇷' : m.asset.country === 'US' ? '🇺🇸' : '🌐'}
                          </span>
                        </div>
                        <div className="text-[11px] text-gray-500 dark:text-gray-400 truncate">{m.asset.name}</div>
                      </div>
                      <div className="text-right">
                        <div className={`text-[13px] font-semibold tnum ${m.variation >= 0 ? 'text-emerald-500 dark:text-emerald-400' : 'text-red-500 dark:text-red-400'}`}>
                          {(m.variation >= 0 ? '+' : '') + (m.variation * 100).toFixed(2)}%
                        </div>
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </Card>
        </div>

        {/* Activity */}
        <Card>
          <SectionTitle
            action={
              <Link to="/lancamentos" className="text-[11px] text-indigo-500 dark:text-indigo-400 hover:opacity-80">
                Ver tudo →
              </Link>
            }
          >
            Atividade recente
          </SectionTitle>
          <ActivityFeed items={recent} assets={assets} />
        </Card>
      </div>
    </AppLayout>
  )
}

/* Spec 35 — discreet amber banner when a snapshot is in review. */
function SnapshotReviewBanner() {
  const inReview = useInReviewSnapshot()
  if (!inReview) return null
  const ym = inReview.period_end_date.slice(0, 7)
  return (
    <div
      className="rounded-xl border border-amber-200 dark:border-amber-900 bg-amber-50 dark:bg-amber-900/20 px-4 py-3 flex items-center gap-3"
      data-testid="dashboard-snapshot-banner"
    >
      <AlertTriangle className="w-4 h-4 text-amber-600 dark:text-amber-400 shrink-0" />
      <div className="flex-1 text-[12px] text-amber-700 dark:text-amber-300">
        Fechamento de <strong>{ym}</strong> em revisão · {inReview.pendencies_open} pendência{inReview.pendencies_open === 1 ? '' : 's'} aberta{inReview.pendencies_open === 1 ? '' : 's'}.
      </div>
      <Link
        to={`/snapshots/${ym}`}
        className="text-[12px] font-medium text-amber-700 dark:text-amber-300 hover:underline"
      >
        Resolver →
      </Link>
    </div>
  )
}

function SnapshotSeries({ snapshots, currentBrl }: { snapshots: SnapshotOut[]; currentBrl: number }) {
  // Order chronologically; show min(12, count) most recent
  const sorted = [...snapshots]
    .sort((a, b) => a.period_end_date.localeCompare(b.period_end_date))
    .slice(-12)

  if (sorted.length === 0) return null

  const values = sorted.map(s => Number(s.total_value_brl))
  const max = Math.max(...values, currentBrl)
  const last = values[values.length - 1]
  const first = values[0]
  const delta = last - first
  const pct = first > 0 ? (delta / first) * 100 : 0

  return (
    <div className="mt-4">
      <div className="flex items-baseline gap-2">
        <div className="text-2xl font-semibold tnum money text-gray-900 dark:text-white">
          {last.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL', notation: 'compact', maximumFractionDigits: 1 })}
        </div>
        <span className={`text-[12px] tnum ${delta >= 0 ? 'text-emerald-500' : 'text-red-500'}`}>
          {delta >= 0 ? '+' : ''}{pct.toFixed(1)}%
        </span>
      </div>
      <div className="mt-2 text-[10px] text-gray-400">
        último snapshot · {new Date(sorted[sorted.length - 1].period_end_date).toLocaleDateString('pt-BR')}
      </div>
      {/* Sparkline */}
      <svg viewBox="0 0 200 60" className="mt-3 w-full h-16" preserveAspectRatio="none">
        <polyline
          fill="none"
          stroke="rgb(99 102 241)"
          strokeWidth="2"
          points={values.map((v, i) => `${(i / Math.max(1, values.length - 1)) * 200},${60 - (v / max) * 55}`).join(' ')}
        />
        <polyline
          fill="rgb(99 102 241 / 0.1)"
          stroke="none"
          points={`0,60 ${values.map((v, i) => `${(i / Math.max(1, values.length - 1)) * 200},${60 - (v / max) * 55}`).join(' ')} 200,60`}
        />
      </svg>
      <div className="mt-1 flex justify-between text-[10px] text-gray-400">
        <span>{new Date(sorted[0].period_end_date).toLocaleDateString('pt-BR', { month: 'short', year: '2-digit' })}</span>
        <span>{new Date(sorted[sorted.length - 1].period_end_date).toLocaleDateString('pt-BR', { month: 'short', year: '2-digit' })}</span>
      </div>
    </div>
  )
}

export function Pill({ label, value, usdValue, hint, money, tone }: {
  label: string
  value: string
  usdValue?: string
  hint?: string
  money?: boolean
  tone?: 'positive' | 'negative' | 'neutral'
}) {
  const toneCls =
    value === '—' ? 'text-gray-400 dark:text-gray-600'
    : tone === 'positive' ? 'text-emerald-500 dark:text-emerald-400'
    : tone === 'negative' ? 'text-red-500 dark:text-red-400'
    : 'text-gray-900 dark:text-white'
  return (
    <div className="px-3 py-2 rounded-lg bg-gray-100 dark:bg-gray-800/50" title={hint}>
      <div className="text-[10px] uppercase tracking-wider text-gray-500 dark:text-gray-400">{label}</div>
      <div className={`text-sm font-semibold tnum ${toneCls}`}>
        {money ? <span className="money">{value}</span> : value}
      </div>
      {usdValue && (
        <div className="text-[10px] tnum money text-gray-500 dark:text-gray-600 mt-0.5">
          {usdValue}
        </div>
      )}
    </div>
  )
}

function EmptyMini({ hint }: { hint: string }) {
  return <div className="text-[11px] text-gray-400 dark:text-gray-600 text-center py-8">{hint}</div>
}

function ActivityFeed({ items, assets }: { items: AssetMovementOut[]; assets: AssetOut[] }) {
  const assetById = useMemo(() => {
    const m = new Map<string, AssetOut>()
    for (const a of assets) m.set(a.id, a)
    return m
  }, [assets])

  if (items.length === 0) {
    return <div className="text-[11px] text-gray-400 dark:text-gray-600 text-center py-8">Sem atividade recente.</div>
  }

  const grouped = new Map<string, AssetMovementOut[]>()
  for (const it of items) {
    const k = it.event_date
    if (!grouped.has(k)) grouped.set(k, [])
    grouped.get(k)!.push(it)
  }
  const dates = Array.from(grouped.keys()).sort((a, b) => b.localeCompare(a))

  return (
    <div className="-mx-1">
      {dates.map(date => (
        <div key={date}>
          <div className="px-1 py-1.5 text-[10px] uppercase tracking-wider text-gray-500 dark:text-gray-400 font-medium">
            {new Date(date).toLocaleDateString('pt-BR', { day: '2-digit', month: 'long', year: 'numeric' })}
          </div>
          {grouped.get(date)!.map(it => {
            const asset = assetById.get(it.asset_id) ?? null
            const klass = asset ? collapsedOf(asset.asset_class) : null
            const color = klass ? KLASS[klass].color : '#94a3b8'
            return (
              <Link
                key={it.id}
                to="/lancamentos"
                className="flex items-center gap-3 px-2 py-2 -mx-1 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800/40 transition-colors"
              >
                <span className="w-1 h-7 rounded-full shrink-0" style={{ background: color }} />
                <span className="inline-flex items-center px-2 py-0.5 rounded-md text-[10px] font-medium uppercase tracking-wider bg-blue-500/15 text-blue-500 dark:text-blue-400 shrink-0">
                  {it.type_label}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-[12px] font-medium text-gray-900 dark:text-white">
                      {asset?.ticker || asset?.name?.slice(0, 24) || '—'}
                    </span>
                  </div>
                  {asset?.name && asset?.ticker && (
                    <div className="text-[11px] text-gray-500 dark:text-gray-400 truncate">{asset.name}</div>
                  )}
                </div>
                <span className="text-[12px] tnum money font-medium text-gray-900 dark:text-white shrink-0">
                  {fmtMoney(it.net_amount, it.currency)}
                </span>
              </Link>
            )
          })}
        </div>
      ))}
    </div>
  )
}
