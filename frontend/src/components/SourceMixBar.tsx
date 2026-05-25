/* Spec 35 — colored mix bar showing the distribution of price sources
 * within a snapshot (API vs Manual vs Upload-required). */

interface Slice {
  label: string
  count: number
  color: string
}

interface Props {
  slices: Slice[]
  /** When false, hides count labels and shows just the bar (compact list mode). */
  showCounts?: boolean
}

export default function SourceMixBar({ slices, showCounts = true }: Props) {
  const total = slices.reduce((s, x) => s + x.count, 0)
  if (total === 0) {
    return <div className="text-[10px] text-gray-400">—</div>
  }
  return (
    <div className="inline-flex flex-col gap-1 min-w-[140px]">
      <div className="flex h-1.5 w-full rounded-sm overflow-hidden">
        {slices.map((s, i) => {
          const pct = (s.count / total) * 100
          if (pct === 0) return null
          return (
            <div
              key={i}
              style={{ width: `${pct}%`, background: s.color }}
              title={`${s.label}: ${s.count}`}
            />
          )
        })}
      </div>
      {showCounts && (
        <div className="flex flex-wrap gap-x-2 text-[10px] text-gray-500">
          {slices.filter(s => s.count > 0).map((s, i) => (
            <span key={i} className="inline-flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full" style={{ background: s.color }} />
              {s.label}: {s.count}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}
