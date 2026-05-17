// Pure-SVG chart primitives — mirror the prototype.
// No external chart library. Recharts/visx can come later if needed.

export interface DonutDatum {
  value: number
  color: string
  label: string
}

export function DonutChart({
  data, size = 200, stroke = 22,
}: {
  data: DonutDatum[]
  size?: number
  stroke?: number
}) {
  const total = data.reduce((s, d) => s + d.value, 0)
  const r = (size - stroke) / 2
  const c = 2 * Math.PI * r
  // Pre-compute cumulative fractions so the render pass doesn't mutate state.
  const cumFractions: number[] = []
  let running = 0
  for (const d of data) {
    cumFractions.push(running)
    if (total > 0) running += d.value / total
  }
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
      <g transform={`translate(${size / 2}, ${size / 2}) rotate(-90)`}>
        <circle r={r} fill="none" stroke="currentColor" strokeOpacity="0.08" strokeWidth={stroke} />
        {total > 0 && data.map((d, i) => {
          const frac = d.value / total
          const dash = c * frac
          const gap = c - dash
          const offset = -c * cumFractions[i]
          return (
            <circle
              key={i}
              r={r}
              fill="none"
              stroke={d.color}
              strokeWidth={stroke}
              strokeDasharray={`${dash} ${gap}`}
              strokeDashoffset={offset}
              strokeLinecap="butt"
            />
          )
        })}
      </g>
    </svg>
  )
}

export function HBar({
  value, max, color = '#6366f1', height = 6,
}: {
  value: number
  max: number
  color?: string
  height?: number
}) {
  const pct = max > 0 ? Math.min(100, (value / max) * 100) : 0
  return (
    <div className="w-full rounded-full bg-gray-200 dark:bg-gray-800 overflow-hidden" style={{ height }}>
      <div className="h-full rounded-full" style={{ width: pct + '%', background: color }} />
    </div>
  )
}
