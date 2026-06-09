import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, type PortfolioOut, type UserOut } from '../lib/api'
import AppLayout from '../components/AppLayout'
import { Card, ClassBadge, FILogo, SectionTitle } from '../components/ui'
import { DonutChart, HBar, type DonutDatum } from '../components/charts'
import Sparkline from '../components/Sparkline'
import { fmtBRL, fmtUSD } from '../lib/money'
import { KLASS, collapsedOf, type CollapsedClassCode } from '../lib/tokens'

function fmtPct(n: number, digits = 1) {
  return (n * 100).toFixed(digits) + '%'
}

const MONTH_SHORT = ['Jan', 'Fev', 'Mar', 'Abr', 'Mai', 'Jun', 'Jul', 'Ago', 'Set', 'Out', 'Nov', 'Dez']

function flagOf(country: string) {
  if (country === 'BR') return '🇧🇷'
  if (country === 'US') return '🇺🇸'
  return '🌐'
}

function labelOfCountry(country: string) {
  if (country === 'BR') return 'Brasil'
  if (country === 'US') return 'EUA'
  return country
}

function colorOfCountry(country: string) {
  if (country === 'BR') return '#22c55e'
  if (country === 'US') return '#3b82f6'
  return '#9ca3af'
}

export default function Portfolio() {
  const navigate = useNavigate()
  const [me, setMe] = useState<UserOut | null>(null)
  const [data, setData] = useState<PortfolioOut | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    api.me().then(setMe).catch(() => navigate('/login'))
  }, [navigate])

  useEffect(() => {
    if (!me) return
    setLoading(true)
    setError('')
    api.getPortfolio()
      .then(setData)
      .catch(e => setError(e instanceof Error ? e.message : 'Erro ao carregar.'))
      .finally(() => setLoading(false))
  }, [me])

  if (!me) return null

  return (
    <AppLayout user={me}>
      {loading && (
        <div className="text-[12px] text-gray-500">Carregando…</div>
      )}
      {error && (
        <div className="rounded-lg border border-red-200 dark:border-red-900 bg-red-50 dark:bg-red-900/20 p-4 text-[13px] text-red-700 dark:text-red-300">
          {error}
        </div>
      )}
      {data && data.source === 'empty' && (
        <div className="rounded-lg border border-dashed border-gray-300 dark:border-gray-700 bg-white/40 dark:bg-gray-900/40 p-12 text-center">
          <p className="text-sm text-gray-500 dark:text-gray-400">Sem snapshots disponíveis.</p>
          <p className="text-xs text-gray-400 dark:text-gray-600 mt-2 max-w-md mx-auto">
            Rode <code className="font-mono">snapshot create</code> ou importe do Notion pra ver o patrimônio aqui.
          </p>
        </div>
      )}
      {data && data.source !== 'empty' && <PortfolioContent data={data} />}
    </AppLayout>
  )
}

function PortfolioContent({ data }: { data: PortfolioOut }) {
  const navigate = useNavigate()
  const ptax = data.ptax_rate ?? 5.12

  // Donut por classe — top 8 + "Outros".
  const allClasses: DonutDatum[] = data.by_class.map(c => ({
    value: c.value_brl,
    color: KLASS[collapsedOf(c.asset_class)]?.color || '#9ca3af',
    label: KLASS[collapsedOf(c.asset_class)]?.label || c.asset_class,
  }))
  const donutClass: DonutDatum[] = allClasses.slice(0, 8)
  const rest = allClasses.slice(8)
  if (rest.length) {
    donutClass.push({
      value: rest.reduce((s, x) => s + x.value, 0),
      color: '#9ca3af',
      label: 'Outros',
    })
  }

  // Donut por país.
  const donutCountry: DonutDatum[] = data.by_country.map(c => ({
    value: c.value_brl,
    color: colorOfCountry(c.country),
    label: labelOfCountry(c.country),
  }))
  const countryTotal = donutCountry.reduce((s, d) => s + d.value, 0)

  const totalInvest = data.total_value_brl

  // Sparkline 12m.
  const sparkData = data.history.map(p => p.total_brl)

  // Stacked bars history.
  const allKlassKeys = Array.from(
    new Set<string>(data.history.flatMap(p => Object.keys(p.by_class))),
  ).sort()
  const maxMonthTotal = Math.max(0, ...data.history.map(p => p.total_brl))

  return (
    <div className="space-y-6">
      {/* Hero */}
      <Card padding="p-6">
        <div className="grid grid-cols-12 gap-6 items-center">
          <div className="col-span-12 lg:col-span-7">
            <div className="text-[11px] font-semibold uppercase tracking-wider text-gray-500">
              Patrimônio investido · {data.as_of}
            </div>
            <div className="mt-2 flex items-baseline gap-3">
              <div className="text-4xl lg:text-5xl font-semibold tracking-tight tnum money">
                {fmtBRL(totalInvest)}
              </div>
            </div>
            <div className="mt-1 flex items-baseline gap-2">
              <div className="text-base text-gray-500 tnum money">
                {fmtUSD(data.total_value_usd)}
              </div>
              <span className="text-[11px] text-gray-500">
                PTAX R$ {ptax.toFixed(4)}
              </span>
            </div>
            <div className="mt-5 grid grid-cols-3 gap-3">
              <div className="px-3 py-2 rounded-lg bg-gray-100 dark:bg-gray-800/50">
                <div className="text-[10px] uppercase tracking-wider text-gray-500">Investido</div>
                <div className="text-sm font-semibold tnum money text-gray-700 dark:text-gray-200">
                  {fmtBRL(data.total_invested_brl, { compact: true })}
                </div>
                <div className="text-[10px] tnum money text-gray-500 dark:text-gray-600 mt-0.5">
                  {fmtUSD(data.total_invested_brl / ptax, { compact: true })}
                </div>
              </div>
              <div className="px-3 py-2 rounded-lg bg-gray-100 dark:bg-gray-800/50">
                <div className="text-[10px] uppercase tracking-wider text-gray-500">Valor atual</div>
                <div className="text-sm font-semibold tnum money text-emerald-500 dark:text-emerald-400">
                  {fmtBRL(totalInvest, { compact: true })}
                </div>
                <div className="text-[10px] tnum money text-gray-500 dark:text-gray-600 mt-0.5">
                  {fmtUSD(data.total_value_usd, { compact: true })}
                </div>
              </div>
              <div className="px-3 py-2 rounded-lg bg-gray-100 dark:bg-gray-800/50">
                <div className="text-[10px] uppercase tracking-wider text-gray-500">Ganho</div>
                <div className={`text-sm font-semibold tnum money ${
                  totalInvest >= data.total_invested_brl
                    ? 'text-emerald-500 dark:text-emerald-400'
                    : 'text-red-500 dark:text-red-400'
                }`}>
                  {fmtBRL(totalInvest - data.total_invested_brl, { compact: true })}
                </div>
                <div className="text-[10px] tnum money text-gray-500 dark:text-gray-600 mt-0.5">
                  {fmtUSD((totalInvest - data.total_invested_brl) / ptax, { compact: true })}
                </div>
              </div>
            </div>
          </div>
          {sparkData.length > 0 && (
            <div className="col-span-12 lg:col-span-5">
              <div className="text-[11px] font-semibold uppercase tracking-wider text-gray-500 mb-3">
                Evolução · {sparkData.length} meses
              </div>
              <Sparkline data={sparkData} w={420} h={130} color="#a78bfa" />
            </div>
          )}
        </div>
      </Card>

      {/* Donuts: classe + país */}
      <div className="grid grid-cols-12 gap-6">
        <Card className="col-span-12 lg:col-span-7">
          <SectionTitle action={<span className="text-[11px] text-gray-500">{data.by_class.length} classes</span>}>
            Por classe
          </SectionTitle>
          <div className="flex items-center gap-6">
            <div className="relative shrink-0">
              <DonutChart data={donutClass} size={260} stroke={28} />
              <div className="absolute inset-0 flex flex-col items-center justify-center">
                <div className="text-[10px] uppercase tracking-wider text-gray-500">Investido</div>
                <div className="text-base font-semibold tnum money">
                  {fmtBRL(totalInvest, { compact: true })}
                </div>
              </div>
            </div>
            <div className="flex-1 space-y-1.5 min-w-0">
              {donutClass.map((d, i) => (
                <div key={i} className="flex items-center gap-2 text-[12px]">
                  <span className="w-2 h-2 rounded-sm shrink-0" style={{ background: d.color }} />
                  <span className="text-gray-700 dark:text-gray-300 truncate">{d.label}</span>
                  <div className="flex-1" />
                  <span className="tnum text-gray-500">{fmtPct(d.value / totalInvest)}</span>
                  <span className="tnum money text-gray-700 dark:text-gray-300 w-20 text-right">
                    {fmtBRL(d.value, { compact: true })}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </Card>

        <Card className="col-span-12 lg:col-span-5">
          <SectionTitle>Por país</SectionTitle>
          <div className="flex items-center gap-4">
            <div className="relative shrink-0">
              <DonutChart data={donutCountry} size={200} stroke={26} />
              <div className="absolute inset-0 flex flex-col items-center justify-center">
                <div className="text-[10px] uppercase tracking-wider text-gray-500">Total</div>
                <div className="text-sm font-semibold tnum money">
                  {fmtBRL(countryTotal, { compact: true })}
                </div>
              </div>
            </div>
            <div className="flex-1 space-y-3">
              {data.by_country.map((c, i) => (
                <div key={i}>
                  <div className="flex items-center justify-between text-[12px] mb-1">
                    <div className="flex items-center gap-2">
                      <span className="text-base">{flagOf(c.country)}</span>
                      <span className="font-medium">{labelOfCountry(c.country)}</span>
                    </div>
                    <span className="tnum text-gray-400">{fmtPct(c.pct)}</span>
                  </div>
                  <HBar value={c.value_brl} max={countryTotal} color={colorOfCountry(c.country)} height={8} />
                  <div className="mt-1 text-[11px] text-gray-500 tnum money">
                    {fmtBRL(c.value_brl, { compact: true })}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </Card>
      </div>

      {/* Por custodiante */}
      <Card>
        <SectionTitle>Por custodiante</SectionTitle>
        <div className="space-y-2">
          {data.by_custodian.map(c => {
            const maxValue = data.by_custodian[0].value_brl
            return (
              <div
                key={c.fi_id}
                className="flex items-center gap-3 p-2 -mx-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800/40 transition-colors cursor-pointer"
                onClick={() => navigate(`/financial-institutions`)}
              >
                <FILogo slug={c.fi_logo_slug} shortName={c.fi_short} size="md" />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-[13px] font-medium">{c.fi_short}</span>
                    <span className="text-[13px] tnum money">{fmtBRL(c.value_brl, { compact: true })}</span>
                  </div>
                  <div className="flex items-center gap-3">
                    <div className="flex-1">
                      <HBar value={c.value_brl} max={maxValue} color="#6366f1" height={4} />
                    </div>
                    <span className="text-[11px] tnum text-gray-500 w-12 text-right">
                      {fmtPct(c.pct, 1)}
                    </span>
                    <span className="text-[11px] text-gray-500 w-16 text-right">
                      {c.asset_count} ativo{c.asset_count !== 1 ? 's' : ''}
                    </span>
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      </Card>

      {/* Histórico — barras empilhadas */}
      {data.history.length > 0 && (
        <Card>
          <SectionTitle action={<span className="text-[11px] text-gray-500">{data.history.length} meses</span>}>
            Composição ao longo do tempo
          </SectionTitle>
          <div className="overflow-x-auto -mx-1">
            <div className="min-w-[800px] flex items-end gap-1 h-48 px-1">
              {data.history.map((row, i) => {
                const monthTotal = row.total_brl
                const heightPct = maxMonthTotal > 0 ? (monthTotal / maxMonthTotal) * 100 : 0
                return (
                  <div key={i} className="flex-1 flex flex-col items-center group">
                    <div
                      className="w-full flex flex-col rounded-md overflow-hidden"
                      style={{ height: `${(heightPct / 100) * 180}px` }}
                      title={`${row.period_end} · ${fmtBRL(monthTotal, { compact: true })}`}
                    >
                      {allKlassKeys.map(klass => {
                        const v = row.by_class[klass] || 0
                        if (v <= 0 || monthTotal <= 0) return null
                        const klassColor = KLASS[collapsedOf(klass) as CollapsedClassCode]?.color || '#9ca3af'
                        return (
                          <div
                            key={klass}
                            style={{
                              background: klassColor,
                              height: `${(v / monthTotal) * 100}%`,
                              opacity: 0.85,
                            }}
                          />
                        )
                      })}
                    </div>
                    <div className="text-[9px] uppercase tracking-wider text-gray-500 mt-1">
                      {MONTH_SHORT[new Date(row.period_end).getMonth()]}
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
          <div className="mt-3 flex items-center gap-2 flex-wrap text-[10px] text-gray-500">
            {allKlassKeys.map(klass => {
              const meta = KLASS[collapsedOf(klass) as CollapsedClassCode]
              if (!meta) return null
              return (
                <span key={klass} className="inline-flex items-center gap-1">
                  <span className="w-2 h-2 rounded-sm" style={{ background: meta.color }} />
                  {meta.label}
                </span>
              )
            })}
          </div>
        </Card>
      )}

      {/* Top 10 holdings */}
      <Card padding="p-3">
        <SectionTitle action={
          <a href="/assets" onClick={e => { e.preventDefault(); navigate('/assets') }}
             className="text-[11px] text-indigo-500 dark:text-indigo-400 hover:text-indigo-700 dark:hover:text-indigo-300">
            Ver todos →
          </a>
        }>
          Top 10 posições
        </SectionTitle>
        <div className="overflow-x-auto -mx-1">
          <table className="w-full text-[12px]">
            <thead>
              <tr className="text-[10px] uppercase tracking-wider text-gray-500">
                <th className="text-left font-medium px-2 py-2">#</th>
                <th className="text-left font-medium px-2 py-2">Ativo</th>
                <th className="text-left font-medium px-2 py-2">Classe</th>
                <th className="text-left font-medium px-2 py-2">Custodiante</th>
                <th className="text-right font-medium px-2 py-2">Valor</th>
                <th className="text-right font-medium px-2 py-2">% portfólio</th>
              </tr>
            </thead>
            <tbody>
              {data.top_holdings.map((h, i) => (
                <tr
                  key={h.asset_id}
                  onClick={() => navigate(`/assets/${h.asset_id}`)}
                  className="border-t border-gray-100 dark:border-gray-800 hover:bg-gray-50 dark:hover:bg-gray-800/30 transition-colors cursor-pointer"
                >
                  <td className="px-2 py-2 tnum text-gray-500">{i + 1}</td>
                  <td className="px-2">
                    <div className="flex items-center gap-2">
                      <span
                        className="w-1 h-5 rounded-full"
                        style={{ background: KLASS[collapsedOf(h.asset_class)]?.color || '#9ca3af' }}
                      />
                      <div>
                        <div className="font-mono font-medium flex items-center gap-1.5">
                          {h.ticker || h.name} <span className="text-[12px]">{flagOf(h.country)}</span>
                        </div>
                        <div className="text-[11px] text-gray-500 truncate max-w-[220px]">{h.name}</div>
                      </div>
                    </div>
                  </td>
                  <td className="px-2">
                    <ClassBadge klass={collapsedOf(h.asset_class)} size="xs" withDot={false} />
                  </td>
                  <td className="px-2">
                    <div className="flex items-center gap-1.5">
                      <FILogo slug={h.fi_logo_slug} shortName={h.fi_short} size="sm" />
                      <span className="text-[11px] text-gray-500 dark:text-gray-400">{h.fi_short}</span>
                    </div>
                  </td>
                  <td className="px-2 text-right">
                    <div className="tnum money font-medium">
                      {fmtBRL(h.value_brl, { compact: true })}
                    </div>
                    <div className="tnum money text-[10px] text-gray-500 dark:text-gray-600">
                      {fmtUSD(h.value_brl / ptax, { compact: true })}
                    </div>
                  </td>
                  <td className="px-2 text-right tnum text-gray-500">{fmtPct(h.pct, 2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  )
}
