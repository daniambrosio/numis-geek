/* Spec 81 — retorno acumulado (chain-linked) do ativo, mês a mês.
 * SVG hand-rolled no mesmo molde de AssetDistributionsChart. Meses sem
 * retorno (null) quebram a série: o acumulado reinicia do zero depois do
 * buraco e o ponto aparece vazio, em vez de fingir continuidade. */
import { useMemo, useState } from 'react'

import type { AssetPerformanceRow } from '../../lib/api'
import { fmtPct } from '../../lib/format'
import { Card, SectionTitle } from '../ui'

const PT_MONTHS = [
  'jan', 'fev', 'mar', 'abr', 'mai', 'jun',
  'jul', 'ago', 'set', 'out', 'nov', 'dez',
]
const W = 1100
const H = 170
const PAD_LEFT = 44
const PAD_RIGHT = 10
const PAD_TOP = 12
const PAD_BOTTOM = 28

function ymLabel(iso: string): string {
  const [y, m] = iso.split('-')
  return `${PT_MONTHS[parseInt(m, 10) - 1]}/${y.slice(2)}`
}

export interface AccPoint {
  date: string
  monthly: number | null
  /** Acumulado desde o início do segmento atual; null quando o mês não tem retorno. */
  acc: number | null
}

/** Chain-link Π(1+r) − 1 em segmentos: um null zera o acumulador. */
export function accumulate(rows: { period_end_date: string; return_pct: number | null }[]): AccPoint[] {
  let acc = 1
  return rows.map(r => {
    if (r.return_pct == null) {
      acc = 1
      return { date: r.period_end_date, monthly: null, acc: null }
    }
    acc *= 1 + r.return_pct
    return { date: r.period_end_date, monthly: r.return_pct, acc: acc - 1 }
  })
}

interface Props {
  /** Linhas em ordem cronológica ASC. */
  rows: AssetPerformanceRow[]
  title?: string
}

export default function AssetReturnChart({ rows, title = 'Retorno acumulado · preço + proventos' }: Props) {
  const points = useMemo(() => accumulate(rows), [rows])
  const [hoverIdx, setHoverIdx] = useState<number | null>(null)

  const valid = points.filter((p): p is AccPoint & { acc: number } => p.acc != null)
  if (points.length < 2 || valid.length === 0) return null

  const maxV = Math.max(0.01, ...valid.map(p => p.acc))
  const minV = Math.min(0, ...valid.map(p => p.acc))
  const plotW = W - PAD_LEFT - PAD_RIGHT
  const plotH = H - PAD_TOP - PAD_BOTTOM
  const stepX = plotW / (points.length - 1)
  const xOf = (i: number) => PAD_LEFT + stepX * i
  const yOf = (v: number) => PAD_TOP + plotH - ((v - minV) / (maxV - minV)) * plotH
  const yZero = yOf(0)

  // Segmentos contínuos (quebram em null).
  const segments: string[] = []
  let cur: string[] = []
  points.forEach((p, i) => {
    if (p.acc == null) {
      if (cur.length > 1) segments.push(cur.join(' '))
      cur = []
      return
    }
    cur.push(`${cur.length === 0 ? 'M' : 'L'} ${xOf(i).toFixed(2)},${yOf(p.acc).toFixed(2)}`)
  })
  if (cur.length > 1) segments.push(cur.join(' '))

  const ticks = [minV, minV + (maxV - minV) / 2, maxV]
  const hover = hoverIdx != null ? points[hoverIdx] : null
  const last = valid[valid.length - 1]

  return (
    <Card padding="p-5">
      <SectionTitle action={
        <span className={`text-[11px] tnum font-medium ${last.acc >= 0 ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-600 dark:text-red-400'}`}>
          {fmtPct(last.acc, 1, true)} até {ymLabel(last.date)}
        </span>
      }>
        {title}
      </SectionTitle>
      <div className="relative mt-2" data-testid="asset-return-chart">
        <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="w-full h-[170px] overflow-visible">
          {ticks.map((t, i) => (
            <g key={i}>
              <line x1={PAD_LEFT} x2={W - PAD_RIGHT} y1={yOf(t)} y2={yOf(t)} stroke="currentColor" strokeOpacity="0.08" />
              <text x={PAD_LEFT - 4} y={yOf(t) + 3} textAnchor="end" fontSize="9" className="fill-gray-500 tnum">
                {fmtPct(t, 0)}
              </text>
            </g>
          ))}
          <line x1={PAD_LEFT} x2={W - PAD_RIGHT} y1={yZero} y2={yZero} stroke="currentColor" strokeOpacity="0.25" />

          {segments.map((d, i) => (
            <g key={i}>
              <path d={`${d} L ${d.split(' ').slice(-1)[0].split(',')[0]},${yZero.toFixed(2)} L ${d.split(' ')[1].split(',')[0]},${yZero.toFixed(2)} Z`}
                fill="#6366f1" fillOpacity="0.10" stroke="none" />
              <path d={d} fill="none" stroke="#6366f1" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
            </g>
          ))}

          {points.map((p, i) => p.acc == null ? (
            <circle key={p.date} cx={xOf(i)} cy={yZero} r="2.5" fill="none" stroke="currentColor" strokeOpacity="0.35" />
          ) : null)}

          {points.map((p, i) => {
            const show = i % 3 === 0 || i === points.length - 1
            if (!show) return null
            return (
              <text key={p.date} x={xOf(i)} y={H - 12} textAnchor="middle" fontSize="9" className="fill-gray-500">
                {ymLabel(p.date)}
              </text>
            )
          })}

          {points.map((p, i) => (
            <rect
              key={`hit-${p.date}`}
              x={xOf(i) - stepX / 2} y={PAD_TOP} width={stepX} height={plotH}
              fill="transparent"
              onMouseEnter={() => setHoverIdx(i)}
              onMouseLeave={() => setHoverIdx(null)}
            />
          ))}
          {hoverIdx != null && (
            <line x1={xOf(hoverIdx)} x2={xOf(hoverIdx)} y1={PAD_TOP} y2={PAD_TOP + plotH}
              stroke="currentColor" strokeOpacity="0.2" strokeDasharray="2 2" />
          )}
        </svg>

        {hover && (
          <div
            className="absolute top-0 right-2 bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 rounded-md shadow-md px-3 py-2 text-[11px] pointer-events-none"
            data-testid="asset-return-tooltip"
          >
            <div className="font-semibold text-gray-700 dark:text-gray-300">{ymLabel(hover.date)}</div>
            <div className="tnum text-gray-500 dark:text-gray-400 mt-0.5">
              no mês: {hover.monthly == null ? '—' : fmtPct(hover.monthly, 2, true)}
            </div>
            <div className="tnum text-indigo-500 dark:text-indigo-400">
              acumulado: {hover.acc == null ? '—' : fmtPct(hover.acc, 2, true)}
            </div>
          </div>
        )}

        <div className="mt-2 flex items-center gap-4 text-[10px] text-gray-500">
          <div className="flex items-center gap-1.5"><span className="w-3 h-[2px] bg-indigo-500" /> Acumulado</div>
          <div className="flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full border border-gray-400" /> Mês sem retorno (buraco reinicia o acumulado)
          </div>
        </div>
      </div>
    </Card>
  )
}
