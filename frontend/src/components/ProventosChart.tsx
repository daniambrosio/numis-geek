/* Spec 31 — Reusable monthly proventos chart.
 *
 * Consumed by /distributions (full) and /dashboard (compact). Renders
 * KPIs, 3 segmented toggles (breakdown · currency · period), stacked
 * bars, hover tooltip and a legend with a synthetic-include checkbox. */
import { useEffect, useMemo, useRef, useState } from 'react'

import {
  api,
  type ChartBreakdown,
  type ChartCurrency,
  type ChartDataOut,
  type ChartPeriod,
} from '../lib/api'
import { computeKpis, fmtChart, fmtPct, monthLabel } from '../lib/chart'
import { Card, GroupingToggle } from './ui'
import ProventosStackedBar from './ProventosStackedBar'

export interface ProventosChartProps {
  defaultBreakdown?: ChartBreakdown
  defaultCurrency?: ChartCurrency
  defaultPeriod?: ChartPeriod
  includeSynthetic?: boolean
  onIncludeSyntheticChange?: (v: boolean) => void
  /** Hide legend + footer toggle. */
  compact?: boolean
  /** Hide the 3 segmented controls. */
  hideToggles?: boolean
  /** Render without the surrounding <Card>. */
  noCard?: boolean
}

const BREAKDOWN_OPTS = [
  { id: 'klass',   label: 'Classe' },
  { id: 'type',    label: 'Tipo' },
  { id: 'country', label: 'País' },
  { id: 'fi',      label: 'FI' },
  { id: 'total',   label: 'Total' },
]
const CURRENCY_OPTS = [
  { id: 'BRL', label: 'R$' },
  { id: 'USD', label: 'US$' },
]
const PERIOD_OPTS = [
  { id: '12m', label: '12M' },
  { id: '24m', label: '24M' },
  { id: 'ytd', label: 'YTD' },
]

export default function ProventosChart({
  defaultBreakdown = 'klass',
  defaultCurrency = 'BRL',
  defaultPeriod = '12m',
  includeSynthetic,
  onIncludeSyntheticChange,
  compact = false,
  hideToggles = false,
  noCard = false,
}: ProventosChartProps) {
  const [breakdown, setBreakdown] = useState<ChartBreakdown>(defaultBreakdown)
  const [currency, setCurrency] = useState<ChartCurrency>(defaultCurrency)
  const [period, setPeriod] = useState<ChartPeriod>(defaultPeriod)
  const [localSynthetic, setLocalSynthetic] = useState(true)
  const synthetic = includeSynthetic ?? localSynthetic

  const [data, setData] = useState<ChartDataOut | null>(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState<string | null>(null)
  const [hovered, setHovered] = useState<number | null>(null)
  const reqIdRef = useRef(0)

  useEffect(() => {
    const reqId = ++reqIdRef.current
    setLoading(true)
    setErr(null)
    api.getDistributionsChart({ period, breakdown, currency, include_synthetic: synthetic })
      .then(d => {
        if (reqId !== reqIdRef.current) return
        setData(d)
      })
      .catch(e => {
        if (reqId !== reqIdRef.current) return
        setErr(e instanceof Error ? e.message : 'Erro')
      })
      .finally(() => {
        if (reqId !== reqIdRef.current) return
        setLoading(false)
      })
  }, [period, breakdown, currency, synthetic])

  function setSynthetic(v: boolean) {
    if (onIncludeSyntheticChange) onIncludeSyntheticChange(v)
    else setLocalSynthetic(v)
  }

  const kpis = useMemo(() => data ? computeKpis(data) : null, [data])

  const hoveredRow = hovered != null && data ? data.rows[hovered] : null

  const body = (
    <>
      {/* Header: KPIs left, toggles right */}
      <div className={`flex items-start justify-between gap-3 flex-wrap ${compact ? 'mb-2' : 'mb-4'}`}>
        <div className={`flex flex-wrap gap-x-5 gap-y-1 ${compact ? 'text-[11px]' : 'text-[12px]'}`}>
          {kpis && (
            <>
              <KpiInline
                label="Último mês"
                value={fmtChart(kpis.lastMonthTotal, currency, compact)}
                sub={kpis.momPct != null ? <Mom value={kpis.momPct} /> : 'MoM —'}
              />
              <KpiInline
                label={period === 'ytd' ? 'YTD' : period === '24m' ? '24M' : '12M'}
                value={fmtChart(kpis.trailingSum, currency, compact)}
                sub={`média/mês ${fmtChart(kpis.monthlyAvg, currency, compact)}`}
              />
              {!compact && (
                <KpiInline
                  label="YTD"
                  value={fmtChart(kpis.ytdSum, currency, true)}
                  sub={`pico ${fmtChart(kpis.max, currency, true)}`}
                />
              )}
            </>
          )}
        </div>

        {!hideToggles && (
          <div className="flex items-center gap-2 flex-wrap">
            <GroupingToggle
              value={breakdown}
              onChange={(v) => setBreakdown(v as ChartBreakdown)}
              options={BREAKDOWN_OPTS}
            />
            <GroupingToggle
              value={currency}
              onChange={(v) => setCurrency(v as ChartCurrency)}
              options={CURRENCY_OPTS}
            />
            <GroupingToggle
              value={period}
              onChange={(v) => setPeriod(v as ChartPeriod)}
              options={PERIOD_OPTS}
            />
          </div>
        )}
      </div>

      {/* Body: chart + tooltip overlay */}
      <div className="relative">
        {loading && !data && (
          <div
            className="flex items-center justify-center text-[11px] text-gray-400"
            style={{ height: compact ? 120 : 180 }}
          >
            Carregando…
          </div>
        )}
        {err && (
          <div className="text-[11px] text-red-500 dark:text-red-400 py-2">{err}</div>
        )}
        {data && (
          <ProventosStackedBar
            data={data}
            hoveredIndex={hovered}
            onHover={setHovered}
            compact={compact}
          />
        )}
        {hoveredRow && (
          <div className="absolute top-0 right-0 max-w-[240px] rounded-lg bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 shadow-lg p-2 pointer-events-none">
            <div className="text-[10px] uppercase tracking-wider text-gray-500 dark:text-gray-400 mb-1">
              {monthLabel(hoveredRow.ym, true)}
            </div>
            <div className="text-[12px] font-semibold tnum mb-1">
              {fmtChart(hoveredRow.total, currency)}
            </div>
            <div className="space-y-0.5">
              {hoveredRow.segments.map(s => (
                <div key={s.key} className="flex items-center gap-1.5 text-[10px]">
                  <span
                    className="w-1.5 h-1.5 rounded-full shrink-0"
                    style={{ background: s.color }}
                  />
                  <span className="flex-1 truncate text-gray-700 dark:text-gray-300">{s.label}</span>
                  <span className="tnum text-gray-500 dark:text-gray-400">
                    {s.value != null && hoveredRow.total > 0
                      ? fmtPct(s.value / hoveredRow.total)
                      : ''}
                  </span>
                  <span className="tnum font-medium">
                    {s.value != null ? fmtChart(s.value, currency, true) : '—'}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Legend + footer toggle (hidden in compact) */}
      {!compact && data && (
        <div className="mt-4 flex items-center justify-between gap-3 flex-wrap">
          <div className="flex flex-wrap gap-x-3 gap-y-1">
            {data.legend.map(s => (
              <div key={s.key} className="inline-flex items-center gap-1.5 text-[11px] text-gray-700 dark:text-gray-300">
                <span className="w-1.5 h-1.5 rounded-full" style={{ background: s.color }} />
                <span>{s.label}</span>
              </div>
            ))}
          </div>
          <label className="inline-flex items-center gap-1.5 text-[11px] text-gray-700 dark:text-gray-300 cursor-pointer">
            <input
              type="checkbox"
              checked={synthetic}
              onChange={(e) => setSynthetic(e.target.checked)}
              className="accent-indigo-500"
            />
            Incluir dividendos sintéticos
          </label>
        </div>
      )}
    </>
  )

  if (noCard) return <div>{body}</div>
  return <Card padding={compact ? 'p-3' : 'p-5'}>{body}</Card>
}

function KpiInline({
  label, value, sub,
}: { label: string; value: string; sub: React.ReactNode }) {
  return (
    <div className="leading-tight">
      <div className="text-[10px] uppercase tracking-wider text-gray-500 dark:text-gray-400">{label}</div>
      <div className="font-semibold tnum text-gray-900 dark:text-white">{value}</div>
      <div className="text-[10px] text-gray-500 dark:text-gray-400">{sub}</div>
    </div>
  )
}

function Mom({ value }: { value: number }) {
  const positive = value >= 0
  const color = positive ? 'text-emerald-500 dark:text-emerald-400' : 'text-red-500 dark:text-red-400'
  return (
    <span className={color}>
      MoM {positive ? '+' : ''}{(value * 100).toFixed(1).replace('.', ',')}%
    </span>
  )
}
