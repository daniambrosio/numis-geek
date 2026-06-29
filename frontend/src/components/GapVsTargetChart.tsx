/**
 * Spec 61c — Gap vs Target Allocation overlay.
 * Each row = one class (or country). Two layers:
 *   - filled bar = current weight
 *   - dashed outline bar = target weight
 * Positive gap (current > target) → tinted red on the right side,
 * negative gap → tinted green (room to grow).
 */
import { KLASS, type CollapsedClassCode } from '../lib/tokens'

interface Slice {
  key: string
  label?: string
  color?: string
  current_pct: number  // 0..1
  target_pct: number
}

interface Props {
  title?: string
  dimension: 'CLASS' | 'COUNTRY'
  slices: Slice[]
}

const COUNTRY_LABEL: Record<string, string> = {
  BR: 'Brasil', US: 'EUA',
}
const COUNTRY_COLOR: Record<string, string> = {
  BR: '#22c55e', US: '#3b82f6',
}

function pct(n: number): string {
  return `${(n * 100).toFixed(1)}%`
}

export default function GapVsTargetChart({ dimension, slices, title }: Props) {
  if (slices.length === 0) {
    return (
      <div className="text-[12px] text-gray-500 italic py-4 text-center">
        Sem dados pra mostrar gap.
      </div>
    )
  }
  const maxScale = Math.max(
    1,
    ...slices.flatMap((s) => [s.current_pct, s.target_pct]),
  ) * 100

  return (
    <div className="space-y-2">
      {title && (
        <div className="text-[11px] uppercase tracking-wider text-gray-500 dark:text-gray-400">
          {title}
        </div>
      )}
      {slices.map((s) => {
        const label =
          s.label ||
          (dimension === 'CLASS'
            ? KLASS[s.key as CollapsedClassCode]?.label || s.key
            : COUNTRY_LABEL[s.key] || s.key)
        const color =
          s.color ||
          (dimension === 'CLASS'
            ? KLASS[s.key as CollapsedClassCode]?.color || '#94a3b8'
            : COUNTRY_COLOR[s.key] || '#94a3b8')
        const curPct = (s.current_pct * 100) / maxScale * 100  // % of available width
        const tgtPct = (s.target_pct * 100) / maxScale * 100
        const delta = s.current_pct - s.target_pct
        const deltaLabel =
          delta === 0 ? 'ok' : (delta > 0 ? `+${pct(delta)}` : pct(delta))
        const deltaTone =
          Math.abs(delta) < 0.005
            ? 'text-gray-500'
            : delta > 0
            ? 'text-red-600 dark:text-red-400'
            : 'text-emerald-600 dark:text-emerald-400'
        return (
          <div key={s.key} data-testid={`gap-row-${s.key}`} className="flex items-center gap-3">
            <div className="w-24 text-[12px] text-gray-700 dark:text-gray-300 truncate">
              {label}
            </div>
            <div className="flex-1 relative h-5 rounded bg-gray-100 dark:bg-gray-800">
              {/* Current fill */}
              <div
                style={{
                  width: `${curPct}%`,
                  background: color,
                  opacity: 0.85,
                }}
                className="absolute inset-y-0 left-0 rounded"
              />
              {/* Target outline */}
              <div
                style={{
                  width: `${tgtPct}%`,
                  borderColor: color,
                }}
                className="absolute inset-y-0 left-0 rounded border-2 border-dashed pointer-events-none"
              />
            </div>
            <div className="w-32 flex justify-end items-center gap-2 text-[11px] tnum">
              <span className="text-gray-700 dark:text-gray-300">{pct(s.current_pct)}</span>
              <span className="text-gray-400 dark:text-gray-600">→</span>
              <span className="text-gray-500 dark:text-gray-500">{pct(s.target_pct)}</span>
            </div>
            <div className={`w-16 text-right text-[11px] tnum font-medium ${deltaTone}`}>
              {deltaLabel}
            </div>
          </div>
        )
      })}
    </div>
  )
}
