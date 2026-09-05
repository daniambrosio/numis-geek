/* Tile de KPI compartilhado (spec 81). Antes existiam três cópias —
 * AssetDetail, SnapshotDetail e CreditCards — com o mesmo shell.
 *
 * `cornerDot` é o ponto de frescor do preço (spec 27); `sub` aceita ReactNode
 * pra compor "há 2h · Finnhub · R$ 430,00". */
import type { ReactNode } from 'react'

export interface KpiTileProps {
  label: string
  value: string
  sub?: ReactNode
  intent?: 'positive' | 'negative'
  cornerDot?: { color: string; title?: string }
  className?: string
}

export default function KpiTile({
  label, value, sub, intent, cornerDot, className = '',
}: KpiTileProps) {
  const intentColor =
    intent === 'negative' ? 'text-red-500 dark:text-red-400'
    : intent === 'positive' ? 'text-emerald-500 dark:text-emerald-400'
    : ''
  return (
    <div
      className={`relative px-4 py-3 rounded-xl bg-gray-50 dark:bg-gray-800/40 border border-gray-200 dark:border-gray-800 ${className}`}
      data-testid="kpi-tile"
    >
      {cornerDot && (
        <span
          className="absolute top-2 right-2 w-1.5 h-1.5 rounded-full"
          style={{ background: cornerDot.color }}
          title={cornerDot.title}
          aria-label={cornerDot.title}
          data-testid="kpi-dot"
        />
      )}
      <div className="text-[11px] uppercase tracking-wider font-medium text-gray-500 dark:text-gray-400">{label}</div>
      <div className={`mt-1 text-lg font-semibold tnum money flex items-center gap-2 ${intentColor}`}>
        {value}
      </div>
      {sub && <div className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">{sub}</div>}
    </div>
  )
}
