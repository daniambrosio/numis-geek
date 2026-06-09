/* Spec 50 parte 2 — bar chart mensal dos proventos do ativo (BRL) com
 * linha de média móvel 12m sobreposta. Últimos 24 meses (fixo) — janela
 * mais ampla esconde sazonalidade. USD aparece no tooltip; o eixo
 * principal é BRL pra não complicar o visual. */
import { useMemo, useState } from 'react'

import type { DistributionOut } from '../lib/api'
import { Card, SectionTitle } from './ui'
import { fmtBRL as fmtBRLBase, fmtUSD as fmtUSDBase } from '../lib/money'

interface Props {
  distributions: DistributionOut[]
}

const PT_MONTHS = [
  'jan', 'fev', 'mar', 'abr', 'mai', 'jun',
  'jul', 'ago', 'set', 'out', 'nov', 'dez',
]

const W = 1100
const H = 160
const PAD_LEFT = 38
const PAD_RIGHT = 8
const PAD_TOP = 12
const PAD_BOTTOM = 28
const WINDOW_MONTHS = 24

function fmtBRL(n: number, compact = false): string {
  return fmtBRLBase(n, { compact, decimals: compact ? 0 : 2 })
}

function fmtUSD(n: number, compact = false): string {
  return fmtUSDBase(n, { compact, decimals: compact ? 0 : 2 })
}

function ymPlus(ym: string, months: number): string {
  const [y, m] = ym.split('-').map(Number)
  let total = y * 12 + (m - 1) + months
  const ny = Math.floor(total / 12)
  const nm = (total % 12) + 1
  return `${ny}-${String(nm).padStart(2, '0')}`
}

function ymLabel(ym: string): string {
  const [y, m] = ym.split('-')
  return `${PT_MONTHS[parseInt(m, 10) - 1]}/${y.slice(2)}`
}

interface Bucket {
  ym: string
  brl: number
  usd: number
  count: number
  byType: Record<string, number>  // type → brl
}

export default function AssetDistributionsChart({ distributions }: Props) {
  const buckets = useMemo<Bucket[]>(() => {
    if (!distributions.length) return []

    // Fold each distribution into BRL/USD per (event_date.slice(0,7)).
    const map = new Map<string, Bucket>()
    for (const d of distributions) {
      const ym = d.event_date.slice(0, 7)
      const fx = d.fx_rate || 0
      const brl = d.currency === 'BRL' ? d.net_amount : d.net_amount * fx
      const usd = d.currency === 'USD'
        ? d.net_amount
        : (fx > 0 ? d.net_amount / fx : 0)
      const bucket = map.get(ym) ?? {
        ym, brl: 0, usd: 0, count: 0, byType: {},
      }
      bucket.brl += brl
      bucket.usd += usd
      bucket.count += 1
      bucket.byType[d.type_label] = (bucket.byType[d.type_label] || 0) + brl
      map.set(ym, bucket)
    }

    // Find the latest month (last distribution's month) and walk back
    // WINDOW_MONTHS keys, filling with zero buckets so the chart shows
    // gaps explicitly rather than implying continuity.
    const ymsAsc = [...map.keys()].sort()
    const lastYm = ymsAsc[ymsAsc.length - 1]
    const out: Bucket[] = []
    for (let i = WINDOW_MONTHS - 1; i >= 0; i--) {
      const ym = ymPlus(lastYm, -i)
      out.push(map.get(ym) ?? { ym, brl: 0, usd: 0, count: 0, byType: {} })
    }
    return out
  }, [distributions])

  // 12-month moving average (BRL) — null until we have 12 prior months.
  const ma12 = useMemo(() => {
    return buckets.map((_, i) => {
      if (i < 11) return null
      let sum = 0
      for (let j = i - 11; j <= i; j++) sum += buckets[j].brl
      return sum / 12
    })
  }, [buckets])

  const [hoverIdx, setHoverIdx] = useState<number | null>(null)

  if (!distributions.length || buckets.length === 0) {
    return null
  }

  const max = Math.max(
    1,
    ...buckets.map(b => b.brl),
    ...ma12.filter((v): v is number => v != null),
  )
  const plotW = W - PAD_LEFT - PAD_RIGHT
  const plotH = H - PAD_TOP - PAD_BOTTOM
  const barSpace = plotW / buckets.length
  const barWidth = Math.max(2, barSpace * 0.6)

  const yOf = (v: number) => PAD_TOP + plotH - (v / max) * plotH
  const xOf = (i: number) => PAD_LEFT + barSpace * (i + 0.5)

  const maPath = ma12
    .map((v, i) => v == null ? null : `${xOf(i).toFixed(2)},${yOf(v).toFixed(2)}`)
    .filter((p): p is string => p != null)
    .reduce((acc, p, i) => acc + (i === 0 ? `M ${p}` : ` L ${p}`), '')

  // Y axis: 4 ticks.
  const yTicks = [0, 0.25, 0.5, 0.75, 1].map(t => ({
    v: max * t,
    y: yOf(max * t),
  }))

  const hover = hoverIdx != null ? buckets[hoverIdx] : null
  const hoverMa = hoverIdx != null ? ma12[hoverIdx] : null

  return (
    <Card padding="p-5">
      <SectionTitle>Proventos mensais (BRL) · média móvel 12m</SectionTitle>
      <div className="relative mt-2" data-testid="asset-distributions-chart">
        <svg
          viewBox={`0 0 ${W} ${H}`}
          preserveAspectRatio="none"
          className="w-full h-[160px] overflow-visible"
        >
          {/* Grid + Y labels */}
          {yTicks.map((t, i) => (
            <g key={i}>
              <line
                x1={PAD_LEFT} x2={W - PAD_RIGHT}
                y1={t.y} y2={t.y}
                stroke="currentColor" strokeOpacity="0.08"
              />
              <text
                x={PAD_LEFT - 4} y={t.y + 3}
                textAnchor="end"
                fontSize="9"
                className="fill-gray-500 dark:fill-gray-500 tnum"
              >
                {fmtBRL(t.v, true)}
              </text>
            </g>
          ))}

          {/* Bars */}
          {buckets.map((b, i) => {
            const y = yOf(b.brl)
            const x = xOf(i) - barWidth / 2
            const h = (PAD_TOP + plotH) - y
            return (
              <rect
                key={b.ym}
                x={x} y={y} width={barWidth} height={Math.max(0, h)}
                rx="1"
                className="fill-emerald-500 dark:fill-emerald-500/80"
                opacity={hoverIdx == null || hoverIdx === i ? 1 : 0.4}
              />
            )
          })}

          {/* 12m moving average line */}
          {maPath && (
            <path
              d={maPath}
              fill="none"
              stroke="#818cf8"
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          )}

          {/* X labels — show every 3rd month to avoid clutter */}
          {buckets.map((b, i) => {
            const show = i % 3 === 0 || i === buckets.length - 1
            if (!show) return null
            return (
              <text
                key={b.ym}
                x={xOf(i)} y={H - 12}
                textAnchor="middle"
                fontSize="9"
                className="fill-gray-500"
              >
                {ymLabel(b.ym)}
              </text>
            )
          })}

          {/* Hover hit areas */}
          {buckets.map((b, i) => (
            <rect
              key={`hit-${b.ym}`}
              x={PAD_LEFT + barSpace * i}
              y={PAD_TOP}
              width={barSpace}
              height={plotH}
              fill="transparent"
              onMouseEnter={() => setHoverIdx(i)}
              onMouseLeave={() => setHoverIdx(null)}
            />
          ))}

          {/* Hover guide line */}
          {hoverIdx != null && (
            <line
              x1={xOf(hoverIdx)} x2={xOf(hoverIdx)}
              y1={PAD_TOP} y2={PAD_TOP + plotH}
              stroke="currentColor" strokeOpacity="0.2"
              strokeDasharray="2 2"
            />
          )}
        </svg>

        {hover && (
          <div
            className="absolute top-0 right-2 bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 rounded-md shadow-md px-3 py-2 text-[11px] pointer-events-none"
            data-testid="asset-distributions-tooltip"
          >
            <div className="font-semibold text-gray-700 dark:text-gray-300">
              {ymLabel(hover.ym)}
            </div>
            <div className="tnum money text-emerald-600 dark:text-emerald-400 mt-0.5">
              {fmtBRL(hover.brl)}
            </div>
            <div className="tnum text-gray-500 dark:text-gray-400">
              {fmtUSD(hover.usd)}
            </div>
            {hoverMa != null && (
              <div className="tnum text-indigo-500 dark:text-indigo-400 mt-0.5">
                MM12: {fmtBRL(hoverMa)}
              </div>
            )}
            {Object.keys(hover.byType).length > 1 && (
              <div className="mt-1.5 pt-1.5 border-t border-gray-200 dark:border-gray-700 space-y-0.5">
                {Object.entries(hover.byType)
                  .sort((a, b) => b[1] - a[1])
                  .map(([t, v]) => (
                    <div key={t} className="flex items-center justify-between gap-3">
                      <span className="text-gray-500">{t}</span>
                      <span className="tnum text-gray-700 dark:text-gray-300">
                        {fmtBRL(v, true)}
                      </span>
                    </div>
                  ))}
              </div>
            )}
          </div>
        )}

        {/* Legend */}
        <div className="mt-2 flex items-center gap-4 text-[10px] text-gray-500">
          <div className="flex items-center gap-1.5">
            <span className="w-3 h-2 bg-emerald-500 rounded-sm" />
            Proventos do mês
          </div>
          <div className="flex items-center gap-1.5">
            <span className="w-3 h-[2px] bg-indigo-500" />
            Média móvel 12m
          </div>
        </div>
      </div>
    </Card>
  )
}
