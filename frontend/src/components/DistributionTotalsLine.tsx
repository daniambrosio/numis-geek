/* Spec 32 — slim totals row.
 * Renders below the chart + by-type card; reacts to the page's filters. */
import { fmtChart } from '../lib/chart'

interface Props {
  netBRL: number
  grossBRL: number
  taxBRL: number
  eventCount: number
}

export default function DistributionTotalsLine({
  netBRL, grossBRL, taxBRL, eventCount,
}: Props) {
  return (
    <div className="text-[12px] text-gray-700 dark:text-gray-300 flex flex-wrap items-center gap-x-3 gap-y-1">
      <span>
        <span className="text-gray-500 dark:text-gray-400">Líquido</span>{' '}
        <span className="font-semibold tnum text-emerald-500 dark:text-emerald-400">
          {fmtChart(netBRL, 'BRL', true)}
        </span>
      </span>
      <span className="text-gray-300 dark:text-gray-700">·</span>
      <span>
        <span className="text-gray-500 dark:text-gray-400">Bruto</span>{' '}
        <span className="tnum">{fmtChart(grossBRL, 'BRL', true)}</span>
      </span>
      <span className="text-gray-300 dark:text-gray-700">·</span>
      <span>
        <span className="text-gray-500 dark:text-gray-400">IR retido</span>{' '}
        <span className="tnum text-amber-600 dark:text-amber-400">
          {fmtChart(taxBRL, 'BRL', true)}
        </span>
      </span>
      <span className="text-gray-300 dark:text-gray-700">·</span>
      <span className="tnum text-gray-500 dark:text-gray-400">
        {eventCount.toLocaleString('pt-BR')} {eventCount === 1 ? 'evento' : 'eventos'}
      </span>
    </div>
  )
}
