interface Props {
  value: number | null
  className?: string
}

/** Spec 38 §6 — visual confidence indicator. Thresholds:
 *  > 0.9 green · 0.7-0.9 amber · < 0.7 red. Null shows "—". */
export default function ConfidencePill({ value, className = '' }: Props) {
  if (value == null) {
    return (
      <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wider bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-400 ${className}`}>
        —
      </span>
    )
  }
  const pct = Math.round(value * 100)
  let cls = 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300'
  if (value < 0.7) {
    cls = 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300'
  } else if (value < 0.9) {
    cls = 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300'
  }
  return (
    <span
      className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wider ${cls} ${className}`}
      title={`confidence ${pct}%`}
      data-testid="confidence-pill"
    >
      {pct}%
    </span>
  )
}
