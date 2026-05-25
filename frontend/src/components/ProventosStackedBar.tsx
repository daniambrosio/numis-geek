/* Spec 31 — Pure stacked-bar renderer for proventos chart.
 *
 * Divs-only (no SVG), rx=2 via Tailwind, opacity 0.85 default → 1 on
 * hover. Reports the hovered row index to the parent so the parent can
 * render a floating tooltip in its own absolute coords. */
import { useMemo } from 'react'

import type { ChartDataOut } from '../lib/api'
import { monthLabel, shouldStrideXAxis } from '../lib/chart'

interface Props {
  data: ChartDataOut
  /** Index of the row hovered (null when none). */
  hoveredIndex: number | null
  onHover: (index: number | null) => void
  /** Compact mode trims the bar height for embed inside Dashboard card. */
  compact?: boolean
}

export default function ProventosStackedBar({
  data, hoveredIndex, onHover, compact,
}: Props) {
  const max = data.totals.max
  const barAreaHeight = compact ? 120 : 180
  const stride = shouldStrideXAxis(data.rows.length)

  // Track which months span year boundaries so the x-axis renders Jan with year suffix.
  const showYearOn = useMemo(() => {
    const out = new Set<string>()
    for (const r of data.rows) {
      if (r.ym.endsWith('-01') || r.ym === data.rows[0].ym) out.add(r.ym)
    }
    return out
  }, [data.rows])

  if (data.rows.length === 0) {
    return (
      <div
        className="flex items-center justify-center text-[11px] text-gray-400"
        style={{ height: barAreaHeight }}
      >
        Sem dados no período.
      </div>
    )
  }

  return (
    <div className="w-full">
      {/* Bars row */}
      <div
        className="flex items-end gap-1 w-full"
        style={{ height: barAreaHeight }}
        role="img"
        aria-label="Proventos por mês"
      >
        {data.rows.map((row, i) => {
          const heightPct = max > 0 ? (row.total / max) * 100 : 0
          const isHovered = hoveredIndex === i
          return (
            <div
              key={row.ym}
              className="flex-1 h-full flex flex-col justify-end cursor-pointer"
              onMouseEnter={() => onHover(i)}
              onMouseLeave={() => onHover(null)}
              data-testid={`bar-${row.ym}`}
            >
              <div
                className={`w-full flex flex-col justify-end overflow-hidden rounded-sm transition-opacity ${
                  isHovered
                    ? 'opacity-100 ring-1 ring-indigo-500/50'
                    : 'opacity-85'
                }`}
                style={{ height: `${heightPct}%`, minHeight: row.total > 0 ? 2 : 0 }}
              >
                {row.segments.map(seg => {
                  const segPct = row.total > 0 && seg.value != null
                    ? (seg.value / row.total) * 100
                    : 0
                  return (
                    <div
                      key={seg.key}
                      style={{ height: `${segPct}%`, background: seg.color }}
                    />
                  )
                })}
              </div>
            </div>
          )
        })}
      </div>

      {/* X-axis labels */}
      <div className="mt-1 flex items-end gap-1 w-full">
        {data.rows.map((row, i) => {
          const show = !stride || i % 2 === 0
          const withYear = showYearOn.has(row.ym)
          return (
            <div
              key={row.ym}
              className="flex-1 text-center text-[10px] text-gray-500 dark:text-gray-400 tnum"
            >
              {show ? monthLabel(row.ym, withYear) : ''}
            </div>
          )
        })}
      </div>
    </div>
  )
}
