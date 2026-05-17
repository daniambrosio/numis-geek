import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import {
  api, type AssetOut, type FinancialInstitutionOut, type LancamentoOut,
  type PositionOut, type UserOut,
} from '../lib/api'
import AppLayout from '../components/AppLayout'
import { Card, SectionTitle, FILogo, CcyPill } from '../components/ui'
import { DonutChart, HBar } from '../components/charts'
import { KLASS, collapsedOf, fiTokenFor, type CollapsedClassCode } from '../lib/tokens'

const OUTROS_COLOR = '#9ca3af'

function fmtBRL(n: number, opts: { compact?: boolean } = {}) {
  if (opts.compact && Math.abs(n) >= 1000) {
    return n.toLocaleString('pt-BR', {
      style: 'currency', currency: 'BRL', notation: 'compact', maximumFractionDigits: 1,
    })
  }
  return n.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })
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
  const [recent, setRecent] = useState<LancamentoOut[]>([])

  useEffect(() => {
    api.me().then(setMe).catch(() => navigate('/login'))
  }, [navigate])

  useEffect(() => {
    if (!me) return
    Promise.all([
      api.listAssets({}),
      api.listFinancialInstitutions(),
      api.listLancamentos({ page_size: 10 }),
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

  const { totalInvested, totalReceived, byClass, byFi, loading } = useMemo(() => {
    let invested = 0
    let received = 0
    const klassMap = new Map<CollapsedClassCode, number>()
    const fiMap = new Map<string, number>()
    let loaded = 0

    for (const a of assets) {
      const p = positions.get(a.id)
      if (p === undefined) continue
      loaded += 1
      if (!p) continue
      invested += Number(p.total_invested_brl ?? 0)
      received += Number(p.total_received_brl ?? 0)
      const klass = collapsedOf(a.asset_class)
      klassMap.set(klass, (klassMap.get(klass) ?? 0) + Number(p.total_invested_brl ?? 0))
      fiMap.set(
        a.financial_institution_id,
        (fiMap.get(a.financial_institution_id) ?? 0) + Number(p.total_invested_brl ?? 0),
      )
    }
    const byClassArr = Array.from(klassMap.entries())
      .map(([k, v]) => ({ klass: k, value: v }))
      .sort((a, b) => b.value - a.value)
    const byFiArr = Array.from(fiMap.entries())
      .map(([id, v]) => ({ fi: id, value: v }))
      .sort((a, b) => b.value - a.value)

    return {
      totalInvested: invested,
      totalReceived: received,
      byClass: byClassArr,
      byFi: byFiArr,
      loading: loaded < assets.length,
    }
  }, [assets, positions])

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
                  {loading && totalInvested === 0 ? '…' : fmtBRL(totalInvested)}
                </div>
                <CcyPill ccy="BRL" />
              </div>
              <div className="mt-1 text-[11px] text-gray-500 dark:text-gray-400">
                Patrimônio total (investimentos + caixa − cartões) chega com specs 10 e 11
              </div>
              <div className="mt-5 grid grid-cols-3 gap-3">
                <Pill label="Investimentos" value={`+ ${fmtBRL(totalInvested, { compact: true })}`} tone="positive" money />
                <Pill label="Caixa" value="—" hint="spec 11 (Transactions)" />
                <Pill label="Cartões abertos" value="—" hint="spec 11 (CreditCard + Invoice)" />
              </div>
              <div className="mt-5 flex items-center gap-2">
                <span className="text-[11px] text-gray-500 dark:text-gray-400">
                  <span className="tnum money font-medium">{fmtBRL(totalReceived, { compact: true })}</span> em proventos acumulados
                  {totalReceived === 0 && <span className="ml-1 text-gray-400">— ativa após spec 08 (Distribution)</span>}
                </span>
              </div>
            </div>
            <div className="col-span-12 lg:col-span-5 p-6 lg:p-8 border-t lg:border-t-0 lg:border-l border-gray-200 dark:border-gray-800 bg-gradient-to-br from-indigo-500/5 to-transparent">
              <div className="text-[11px] font-semibold uppercase tracking-wider text-gray-500 dark:text-gray-400">
                Evolução · 12 meses
              </div>
              <div className="mt-6 rounded-xl border border-dashed border-gray-300 dark:border-gray-700 p-6 text-center">
                <div className="text-[11px] text-gray-500 dark:text-gray-400">Spec futura</div>
                <div className="text-[10px] text-gray-400 dark:text-gray-600 mt-1">
                  Requer snapshot mensal de patrimônio
                </div>
              </div>
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
                      {fmtBRL(totalInvested, { compact: true })}
                    </div>
                  </div>
                </div>
                <div className="flex-1 space-y-1.5 min-w-0">
                  {donutData.map((d, i) => {
                    const pct = totalInvested ? d.value / totalInvested : 0
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
            <PlaceholderCard hint="ativa com spec 09 (Asset.country)" />
          </Card>

          <Card className="col-span-12 lg:col-span-4">
            <SectionTitle action={<span className="text-[11px] text-gray-500">12 meses</span>}>
              Proventos recebidos
            </SectionTitle>
            <div>
              <div className="text-2xl font-semibold tnum money text-gray-900 dark:text-white">
                {fmtBRL(totalReceived)}
              </div>
              <div className="text-[11px] text-gray-500 dark:text-gray-400 mt-0.5">
                Acumulado · spec 08 separa em Dividendos / Juros / JCP / Aluguel
              </div>
            </div>
            <div className="mt-5 pt-4 border-t border-gray-200 dark:border-gray-800 grid grid-cols-3 gap-2 text-[11px]">
              <Stat label="Dividendos" value="—" />
              <Stat label="Juros / JCP" value="—" />
              <Stat label="Aluguel" value="—" />
            </div>
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
                  const pct = totalInvested ? f.value / totalInvested : 0
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
            <SectionTitle>Top movers · 30 dias</SectionTitle>
            <PlaceholderCard hint="ativa com spec 09 (current_price)" />
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

function Pill({ label, value, hint, money, tone }: {
  label: string
  value: string
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
    </div>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-gray-500 dark:text-gray-400 uppercase tracking-wider text-[10px]">{label}</div>
      <div className={`tnum font-medium ${value === '—' ? 'text-gray-300 dark:text-gray-700' : 'text-gray-900 dark:text-white money'}`}>
        {value}
      </div>
    </div>
  )
}

function PlaceholderCard({ hint }: { hint: string }) {
  return (
    <div className="rounded-xl border border-dashed border-gray-300 dark:border-gray-700 p-6 text-center">
      <div className="text-[11px] text-gray-500 dark:text-gray-400">Em breve</div>
      <div className="text-[10px] text-gray-400 dark:text-gray-600 mt-1">{hint}</div>
    </div>
  )
}

function EmptyMini({ hint }: { hint: string }) {
  return <div className="text-[11px] text-gray-400 dark:text-gray-600 text-center py-8">{hint}</div>
}

function ActivityFeed({ items, assets }: { items: LancamentoOut[]; assets: AssetOut[] }) {
  const assetById = useMemo(() => {
    const m = new Map<string, AssetOut>()
    for (const a of assets) m.set(a.id, a)
    return m
  }, [assets])

  if (items.length === 0) {
    return <div className="text-[11px] text-gray-400 dark:text-gray-600 text-center py-8">Sem atividade recente.</div>
  }

  const grouped = new Map<string, LancamentoOut[]>()
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
                <CcyPill ccy={it.currency} />
              </Link>
            )
          })}
        </div>
      ))}
    </div>
  )
}
