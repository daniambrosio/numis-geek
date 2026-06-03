/* Spec 50 — Asset Detail · Tabela + sparkline dos fechamentos do ativo.
 *
 * Renderiza um card embaixo dos KPIs em /assets/{id}. Cada linha vem de
 * um CLOSED PortfolioSnapshot onde o ativo tinha um item. Δ MoM é
 * calculado client-side comparando market_value_brl entre meses
 * adjacentes (a API já devolve ordenado desc). */
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'

import type {
  AssetMovementOut,
  AssetSnapshotHistoryOut,
} from '../lib/api'
import { Card, SectionTitle } from './ui'

interface Props {
  history: AssetSnapshotHistoryOut | null
  loading?: boolean
  assetId: string
  /** Movements pra agregação mensal de aportes (BUYs). */
  movements?: AssetMovementOut[]
}

function fmtBRL(n: number | null | undefined): string {
  if (n == null) return '—'
  return n.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })
}

function fmtUSD(n: number | null | undefined): string {
  if (n == null) return '—'
  return n.toLocaleString('en-US', { style: 'currency', currency: 'USD' })
}

function fmtQty(n: number): string {
  return n.toLocaleString('pt-BR', {
    minimumFractionDigits: n < 1 ? 4 : 0,
    maximumFractionDigits: n < 1 ? 6 : 4,
  })
}

function fmtPct(n: number, sign = true): string {
  const v = (n * 100).toFixed(2)
  return (sign && n > 0 ? '+' : '') + v + '%'
}

const PT_MONTHS = [
  'Jan', 'Fev', 'Mar', 'Abr', 'Mai', 'Jun',
  'Jul', 'Ago', 'Set', 'Out', 'Nov', 'Dez',
]

function fmtPeriod(iso: string): string {
  const [y, m] = iso.split('-')
  const month = PT_MONTHS[parseInt(m, 10) - 1] ?? m
  return `${month}/${y.slice(2)}`
}

function ymOf(iso: string): string {
  return iso.slice(0, 7)
}

// SVG chart constants
const CHART_W = 1100
const CHART_H = 110
const CHART_PAD_LEFT = 8
const CHART_PAD_RIGHT = 8
const CHART_PAD_TOP = 12
const CHART_PAD_BOTTOM = 18

export default function AssetSnapshotsCard({
  history, loading, assetId, movements,
}: Props) {
  const rows = history?.items ?? []

  // Chronological asc for chart drawing.
  const ascItems = useMemo(() => [...rows].reverse(), [rows])

  // Aporte (BUYs) por YM no mesmo período da timeline do gráfico.
  // Source of truth: net_amount em BRL (já reflete fee/tax e fx_rate
  // pra USD). BUYs em USD são convertidos via fx_rate.
  const aportesByYm = useMemo(() => {
    const out = new Map<string, number>()
    if (!movements) return out
    for (const m of movements) {
      if (m.type !== 'BUY' && m.type !== 'SUBSCRIPTION') continue
      if (m.is_active === false) continue
      const ym = m.event_date.slice(0, 7)
      const fx = m.fx_rate || 1
      // net_amount é positivo no backend (gross + fee + tax). Convertemos
      // pra BRL pra alinhar com a linha (que é market_value_brl).
      const cash = Math.abs(m.net_amount)
      const brl = m.currency === 'BRL' ? cash : cash * fx
      out.set(ym, (out.get(ym) ?? 0) + brl)
    }
    return out
  }, [movements])

  const [hoverIdx, setHoverIdx] = useState<number | null>(null)

  if (loading) {
    return (
      <Card padding="p-5">
        <SectionTitle>Fechamentos</SectionTitle>
        <div className="text-[12px] text-gray-400 py-4 text-center">
          Carregando…
        </div>
      </Card>
    )
  }

  if (!rows.length) {
    return (
      <Card padding="p-5">
        <SectionTitle>Fechamentos</SectionTitle>
        <div className="text-[12px] text-gray-400 py-4 text-center">
          Sem fechamentos ainda — o ativo aparecerá aqui depois que o
          primeiro snapshot mensal for confirmado.
        </div>
      </Card>
    )
  }

  return (
    <Card padding="p-5">
      <div className="flex items-center justify-between mb-3">
        <SectionTitle>Fechamentos</SectionTitle>
        <span className="text-[10px] text-gray-500">
          {rows.length} fechamento{rows.length === 1 ? '' : 's'} ·
          {' '}apenas confirmados
        </span>
      </div>

      {ascItems.length >= 2 && (() => {
        const linePts = ascItems.map(it => Number(it.market_value_brl ?? 0))
        const maxLine = Math.max(1, ...linePts)
        const aportes = ascItems.map(it => aportesByYm.get(ymOf(it.period_end_date)) ?? 0)
        const maxAporte = Math.max(0, ...aportes)
        const plotW = CHART_W - CHART_PAD_LEFT - CHART_PAD_RIGHT
        const plotH = CHART_H - CHART_PAD_TOP - CHART_PAD_BOTTOM
        const stepX = plotW / (ascItems.length - 1)
        const xOf = (i: number) => CHART_PAD_LEFT + stepX * i
        const yLineOf = (v: number) => CHART_PAD_TOP + plotH - (v / maxLine) * plotH
        // Bars share the visible plot area but max at 60% to not overpower
        // the line.
        const yAporteOf = (v: number) =>
          maxAporte === 0
            ? CHART_PAD_TOP + plotH
            : CHART_PAD_TOP + plotH - (v / maxAporte) * plotH * 0.6

        const linePath = linePts
          .map((v, i) => `${xOf(i).toFixed(2)},${yLineOf(v).toFixed(2)}`)
          .reduce((acc, p, i) => acc + (i === 0 ? `M ${p}` : ` L ${p}`), '')
        const areaPath = linePath + ` L ${xOf(linePts.length - 1).toFixed(2)},${(CHART_PAD_TOP + plotH).toFixed(2)} L ${xOf(0).toFixed(2)},${(CHART_PAD_TOP + plotH).toFixed(2)} Z`

        const barWidth = Math.max(2, Math.min(10, stepX * 0.4))
        const hovered = hoverIdx != null ? ascItems[hoverIdx] : null
        const hoveredAporte = hoverIdx != null ? aportes[hoverIdx] : 0

        return (
          <div className="relative mb-4 -mx-1">
            <svg
              viewBox={`0 0 ${CHART_W} ${CHART_H}`}
              preserveAspectRatio="none"
              className="w-full overflow-visible"
              data-testid="snapshot-evolution-chart"
            >
              {/* Area under line */}
              <path d={areaPath} fill="#818cf8" fillOpacity="0.12" />
              {/* Line */}
              <path
                d={linePath}
                fill="none"
                stroke="#818cf8"
                strokeWidth="1.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
              {/* Aporte bars (indigo, semi-transparent) */}
              {aportes.map((v, i) => {
                if (v <= 0) return null
                const y = yAporteOf(v)
                const h = (CHART_PAD_TOP + plotH) - y
                return (
                  <rect
                    key={ascItems[i].period_end_date}
                    x={xOf(i) - barWidth / 2}
                    y={y}
                    width={barWidth}
                    height={Math.max(1, h)}
                    rx="1"
                    className="fill-indigo-500"
                    opacity="0.55"
                  />
                )
              })}
              {/* Hover hit areas */}
              {ascItems.map((it, i) => (
                <rect
                  key={`hit-${it.period_end_date}`}
                  x={i === 0 ? 0 : xOf(i) - stepX / 2}
                  y={0}
                  width={i === 0 || i === ascItems.length - 1 ? stepX / 2 : stepX}
                  height={CHART_H}
                  fill="transparent"
                  onMouseEnter={() => setHoverIdx(i)}
                  onMouseLeave={() => setHoverIdx(null)}
                />
              ))}
              {hoverIdx != null && (
                <>
                  <line
                    x1={xOf(hoverIdx)} x2={xOf(hoverIdx)}
                    y1={CHART_PAD_TOP} y2={CHART_PAD_TOP + plotH}
                    stroke="currentColor" strokeOpacity="0.2"
                    strokeDasharray="2 2"
                  />
                  <circle
                    cx={xOf(hoverIdx)}
                    cy={yLineOf(linePts[hoverIdx])}
                    r="3"
                    fill="#818cf8"
                  />
                </>
              )}
            </svg>
            {hovered && (
              <div className="absolute top-0 right-2 bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 rounded-md shadow-md px-3 py-2 text-[11px] pointer-events-none">
                <div className="font-semibold text-gray-700 dark:text-gray-300">
                  {fmtPeriod(hovered.period_end_date)}
                </div>
                <div className="tnum money text-indigo-500 mt-0.5">
                  {fmtBRL(Number(hovered.market_value_brl ?? 0))}
                </div>
                {hoveredAporte > 0 && (
                  <div className="tnum text-emerald-600 dark:text-emerald-400">
                    Aporte: {fmtBRL(hoveredAporte)}
                  </div>
                )}
              </div>
            )}
            <div className="flex items-center gap-4 text-[10px] text-gray-500 mt-1 px-2">
              <div className="flex items-center gap-1.5">
                <span className="w-3 h-[2px] bg-indigo-500" />
                Valor BRL no fechamento
              </div>
              {maxAporte > 0 && (
                <div className="flex items-center gap-1.5">
                  <span className="w-3 h-2 bg-indigo-500/55 rounded-sm" />
                  Aporte no mês
                </div>
              )}
            </div>
          </div>
        )
      })()}

      <div className="overflow-x-auto">
        <table className="w-full text-[12px]" data-testid="asset-snapshots-table">
          <thead>
            <tr className="text-[10px] uppercase tracking-wider text-gray-500 border-b border-gray-200 dark:border-gray-800">
              <th className="text-left font-medium py-2 px-2">Período</th>
              <th className="text-right font-medium py-2 px-2">Qtd</th>
              <th className="text-right font-medium py-2 px-2">Preço fim</th>
              <th className="text-right font-medium py-2 px-2">Valor BRL</th>
              <th className="text-right font-medium py-2 px-2">Valor USD</th>
              <th className="text-right font-medium py-2 px-2">Δ MoM</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((it, idx) => {
              const ym = ymOf(it.period_end_date)
              const cur = it.market_value_brl != null ? Number(it.market_value_brl) : null
              // rows[idx + 1] is the chronologically previous month (desc list).
              const prev = rows[idx + 1]
              const prevVal = prev?.market_value_brl != null ? Number(prev.market_value_brl) : null
              const delta = cur != null && prevVal != null && prevVal > 0
                ? (cur - prevVal) / prevVal
                : null
              const deltaCls = delta == null
                ? 'text-gray-400'
                : delta > 0
                  ? 'text-emerald-600 dark:text-emerald-400'
                  : delta < 0
                    ? 'text-red-600 dark:text-red-400'
                    : 'text-gray-500'
              const qty = Number(it.quantity)
              const up = it.unit_price != null ? Number(it.unit_price) : null
              const usd = it.market_value_usd != null ? Number(it.market_value_usd) : null
              return (
                <tr
                  key={it.period_end_date}
                  className="border-b border-gray-100 dark:border-gray-800/60 hover:bg-gray-50 dark:hover:bg-gray-800/40"
                  data-testid="asset-snapshots-row"
                >
                  <td className="py-2 px-2">
                    <Link
                      to={`/snapshots/${ym}`}
                      state={{ from: `/assets/${assetId}`, fromLabel: 'ativo' }}
                      className="text-indigo-500 hover:text-indigo-300"
                    >
                      {fmtPeriod(it.period_end_date)}
                    </Link>
                  </td>
                  <td className="py-2 px-2 text-right tnum text-gray-700 dark:text-gray-300">
                    {qty === 0 ? '—' : fmtQty(qty)}
                  </td>
                  <td className="py-2 px-2 text-right tnum text-gray-700 dark:text-gray-300">
                    {up == null ? '—' : up.toLocaleString('pt-BR', {
                      style: 'currency',
                      currency: history?.currency ?? 'BRL',
                    })}
                  </td>
                  <td className="py-2 px-2 text-right tnum text-gray-700 dark:text-gray-300">
                    {fmtBRL(cur)}
                  </td>
                  <td className="py-2 px-2 text-right tnum text-gray-700 dark:text-gray-300">
                    {fmtUSD(usd)}
                  </td>
                  <td className={`py-2 px-2 text-right tnum ${deltaCls}`}>
                    {delta == null ? '—' : fmtPct(delta)}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </Card>
  )
}
