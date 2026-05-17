import { Search, ArrowUpRight, ArrowDownRight, Sparkles, CornerDownLeft } from 'lucide-react'
import { KLASS, fiTokenFor, lanTypeColor, type CollapsedClassCode } from '../lib/tokens'

/* ────────────────────────────────────────────────────────────
 * Reusable UI primitives — mirror prototype's components.
 * Card / PageHeader / SearchInput / ToggleSwitch / MultiChips
 * FilterGroup / GroupingToggle / ClassBadge / CcyPill / FILogo
 * ────────────────────────────────────────────────────────── */

export function Card({
  children,
  className = '',
  padding = 'p-5',
}: {
  children: React.ReactNode
  className?: string
  padding?: string
}) {
  return (
    <div className={`rounded-2xl bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 ${padding} ${className}`}>
      {children}
    </div>
  )
}

export function PageHeader({
  title,
  count,
  countLabel,
  action,
}: {
  title: string
  count?: number | null
  countLabel?: string
  action?: React.ReactNode
}) {
  return (
    <Card>
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-gray-900 dark:text-white">{title}</h1>
          {count != null && (
            <p className="text-[12px] text-gray-500 dark:text-gray-400 mt-0.5">
              <span className="tnum">{count}</span> {countLabel}
            </p>
          )}
        </div>
        {action}
      </div>
    </Card>
  )
}

export function SearchInput({
  value,
  onChange,
  placeholder = 'Buscar…',
  className = 'w-48',
}: {
  value: string
  onChange: (v: string) => void
  placeholder?: string
  className?: string
}) {
  return (
    <div className="relative">
      <Search className="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-500" />
      <input
        value={value}
        onChange={e => onChange(e.target.value)}
        placeholder={placeholder}
        className={`h-8 pl-7 pr-3 text-[12px] rounded-lg bg-gray-100 dark:bg-gray-900 border border-gray-200 dark:border-gray-800 placeholder:text-gray-500 focus:outline-none focus:border-indigo-500 transition-colors ${className}`}
      />
    </div>
  )
}

export function ToggleSwitch({
  on,
  onChange,
  label,
}: {
  on: boolean
  onChange: (v: boolean) => void
  label: string
}) {
  return (
    <label className="inline-flex items-center gap-2 cursor-pointer text-[11px] text-gray-600 dark:text-gray-400 select-none">
      <button
        type="button"
        onClick={() => onChange(!on)}
        className={`w-7 h-4 rounded-full p-0.5 flex items-center transition-colors ${
          on ? 'bg-indigo-500 justify-end' : 'bg-gray-300 dark:bg-gray-700 justify-start'
        }`}
      >
        <span className="w-3 h-3 rounded-full bg-white shadow-sm" />
      </button>
      {label}
    </label>
  )
}

export interface ChipOption {
  id: string
  label: string
  color?: string | null
  disabled?: boolean
}

export function MultiChips({
  options,
  selected,
  onChange,
}: {
  options: ChipOption[]
  selected: string[]
  onChange: (next: string[]) => void
}) {
  return (
    <div className="flex items-center gap-1.5 flex-wrap">
      {options.map(opt => {
        const active = selected.includes(opt.id)
        const disabled = !!opt.disabled
        return (
          <button
            key={opt.id}
            type="button"
            disabled={disabled}
            onClick={() => {
              if (disabled) return
              onChange(active ? selected.filter(s => s !== opt.id) : [...selected, opt.id])
            }}
            className={`inline-flex items-center gap-1.5 px-2 py-1 rounded-md text-[11px] font-medium transition-colors ${
              active
                ? 'bg-indigo-500/15 text-indigo-700 dark:text-indigo-300 border border-indigo-500/40'
                : disabled
                ? 'bg-transparent text-gray-400 dark:text-gray-600 border border-dashed border-gray-200 dark:border-gray-800 cursor-not-allowed'
                : 'bg-transparent text-gray-500 dark:text-gray-400 border border-gray-200 dark:border-gray-800 hover:border-gray-400 dark:hover:border-gray-700'
            }`}
          >
            {opt.color && <span className="w-1.5 h-1.5 rounded-full" style={{ background: opt.color }} />}
            {opt.label}
          </button>
        )
      })}
    </div>
  )
}

export function FilterGroup({
  label,
  children,
  action,
}: {
  label: string
  children: React.ReactNode
  action?: React.ReactNode
}) {
  return (
    <div className="flex items-start gap-3">
      <span className="text-[10px] uppercase tracking-wider text-gray-500 dark:text-gray-400 font-medium pt-1.5 min-w-[90px] shrink-0">
        {label}
      </span>
      <div className="flex items-center gap-1.5 flex-wrap min-w-0 flex-1">{children}</div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  )
}

export interface GroupingOption {
  id: string
  label: string
}

export function GroupingToggle({
  value,
  onChange,
  options,
}: {
  value: string
  onChange: (v: string) => void
  options: GroupingOption[]
}) {
  return (
    <div className="inline-flex items-center rounded-lg p-0.5 bg-gray-100 dark:bg-gray-900 border border-gray-200 dark:border-gray-800">
      {options.map(opt => (
        <button
          key={opt.id}
          type="button"
          onClick={() => onChange(opt.id)}
          className={`px-2.5 h-7 text-[11px] font-medium rounded-md transition-colors ${
            value === opt.id
              ? 'bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 shadow-sm'
              : 'text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'
          }`}
        >
          {opt.label}
        </button>
      ))}
    </div>
  )
}

export function ClassBadge({
  klass,
  withDot = true,
  size = 'sm',
}: {
  klass: CollapsedClassCode
  withDot?: boolean
  size?: 'xs' | 'sm'
}) {
  const meta = KLASS[klass]
  if (!meta) return null
  const sizeCls = size === 'xs' ? 'text-[10px] px-1.5 py-0.5' : 'text-[11px] px-2 py-0.5'
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-md font-medium bg-gray-100 dark:bg-gray-800/70 text-gray-700 dark:text-gray-300 ${sizeCls}`}>
      {withDot && <span className="w-1.5 h-1.5 rounded-full" style={{ background: meta.color }} />}
      {meta.label}
    </span>
  )
}

export function CcyPill({ ccy, className = '' }: { ccy: 'BRL' | 'USD'; className?: string }) {
  return (
    <span
      className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold tracking-wide ${
        ccy === 'USD' ? 'bg-emerald-500/15 text-emerald-400' : 'bg-amber-600/15 text-amber-500'
      } ${className}`}
    >
      {ccy}
    </span>
  )
}

export function QuickAddBar({
  placeholder,
  onClick,
}: {
  placeholder: string
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="w-full flex items-center gap-3 px-4 py-3 rounded-2xl bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 hover:border-indigo-400 dark:hover:border-indigo-500/50 transition-colors text-left group"
    >
      <Sparkles className="w-4 h-4 text-indigo-500 dark:text-indigo-400 shrink-0" />
      <span className="text-[13px] text-gray-400 dark:text-gray-500 truncate flex-1">{placeholder}</span>
      <kbd className="inline-flex items-center gap-0.5 rounded border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-950 px-1.5 py-0.5 text-[10px] font-mono text-gray-400 dark:text-gray-500">
        <CornerDownLeft className="w-2.5 h-2.5" />
      </kbd>
    </button>
  )
}

export function TypeBadge({ code, label }: { code: string; label: string }) {
  const color = lanTypeColor(code)
  return (
    <span
      className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wider"
      style={{ background: `${color}26`, color }}
    >
      {label}
    </span>
  )
}

export function SectionTitle({
  children,
  action,
}: {
  children: React.ReactNode
  action?: React.ReactNode
}) {
  return (
    <div className="flex items-center justify-between mb-3">
      <h3 className="text-[11px] font-semibold uppercase tracking-wider text-gray-500 dark:text-gray-400">{children}</h3>
      {action}
    </div>
  )
}

export function Trend({ value, suffix }: { value: number; suffix?: string }) {
  const positive = value >= 0
  return (
    <span
      className={`inline-flex items-center gap-0.5 text-[11px] font-medium tnum ${
        positive ? 'text-emerald-500 dark:text-emerald-400' : 'text-red-500 dark:text-red-400'
      }`}
    >
      {positive ? <ArrowUpRight className="w-3 h-3" /> : <ArrowDownRight className="w-3 h-3" />}
      {(positive ? '+' : '') + (value * 100).toFixed(2)}%
      {suffix && <span className="text-gray-500 dark:text-gray-400 ml-0.5">{suffix}</span>}
    </span>
  )
}

export function FILogo({
  slug,
  shortName,
  size = 'md',
}: {
  slug: string | null
  shortName: string
  size?: 'sm' | 'md' | 'lg'
}) {
  const tok = fiTokenFor(slug, shortName)
  const px = size === 'lg' ? 'w-10 h-10 text-sm' : size === 'sm' ? 'w-6 h-6 text-[10px]' : 'w-8 h-8 text-xs'
  return (
    <div
      className={`flex items-center justify-center rounded-md font-semibold text-white shrink-0 ${px}`}
      style={{ background: tok.color }}
      title={shortName}
    >
      {tok.initials}
    </div>
  )
}
