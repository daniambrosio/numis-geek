import type { Verdict } from '../lib/api'

interface Props {
  verdict: Verdict
  title?: string
  size?: 'sm' | 'md'
}

const STYLES: Record<Verdict, { bg: string; text: string; label: string }> = {
  BUY: {
    bg: 'bg-emerald-500/15',
    text: 'text-emerald-700 dark:text-emerald-300',
    label: 'Comprar',
  },
  HOLD: {
    bg: 'bg-gray-500/15',
    text: 'text-gray-700 dark:text-gray-300',
    label: 'Manter',
  },
  SELL: {
    bg: 'bg-red-500/15',
    text: 'text-red-700 dark:text-red-300',
    label: 'Vender',
  },
  NA: {
    bg: 'bg-gray-200 dark:bg-gray-800',
    text: 'text-gray-500 dark:text-gray-500',
    label: '—',
  },
}

export default function VerdictBadge({ verdict, title, size = 'md' }: Props) {
  const s = STYLES[verdict]
  const cls =
    size === 'sm'
      ? 'px-1.5 py-0.5 text-[10px]'
      : 'px-2 py-0.5 text-[11px]'
  return (
    <span
      title={title}
      className={`inline-flex items-center rounded-full font-semibold ${cls} ${s.bg} ${s.text}`}
    >
      {s.label}
    </span>
  )
}
