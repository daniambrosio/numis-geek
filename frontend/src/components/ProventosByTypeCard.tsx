/* Spec 32 — "Por tipo" 5-chip card.
 *
 * Always renders the 5 categories in fixed order (DIVIDEND, INTEREST,
 * JCP, SECURITIES_LENDING, OPTION_PREMIUM). OPTION_PREMIUM gets an
 * [OPÇÕES] badge and dims to a dashed/60% state when synthetic is off. */
import { useEffect, useState } from 'react'

import {
  api,
  type ChartCurrency,
  type ChartDataOut,
  type ChartPeriod,
} from '../lib/api'
import { fmtChart, fmtPct } from '../lib/chart'
import { Card } from './ui'

const TYPE_ORDER = [
  'DIVIDEND', 'INTEREST', 'JCP', 'SECURITIES_LENDING', 'OPTION_PREMIUM',
] as const

const TYPE_COLOR: Record<string, string> = {
  DIVIDEND:           '#22c55e',
  INTEREST:           '#3b82f6',
  JCP:                '#f59e0b',
  SECURITIES_LENDING: '#8b5cf6',
  OPTION_PREMIUM:     '#a855f7',
}

const TYPE_LABEL: Record<string, string> = {
  DIVIDEND:           'Dividendo',
  INTEREST:           'Juros / Cupom',
  JCP:                'JCP',
  SECURITIES_LENDING: 'Aluguel',
  OPTION_PREMIUM:     'Prêmio sintético',
}

interface Props {
  /** When false, OPTION_PREMIUM renders in dim/dashed state (sub: "desligado"). */
  includeSynthetic: boolean
  /** Currency for displayed values; passed through to the chart endpoint. */
  currency?: ChartCurrency
  /** Period for the underlying totals. */
  period?: ChartPeriod
}

export default function ProventosByTypeCard({
  includeSynthetic, currency = 'BRL', period = '12m',
}: Props) {
  const [data, setData] = useState<ChartDataOut | null>(null)
  const [loading, setLoading] = useState(true)

  // Always fetch with include_synthetic=true so the OPTION_PREMIUM total
  // is available for the share computation. The dim state is purely UI.
  useEffect(() => {
    setLoading(true)
    api.getDistributionsChart({
      period, breakdown: 'type', currency, include_synthetic: true,
    })
      .then(setData)
      .finally(() => setLoading(false))
  }, [period, currency])

  // Sum per type across all rows
  const totalsByType: Record<string, number> = {}
  let grandTotal = 0
  if (data) {
    for (const row of data.rows) {
      for (const seg of row.segments) {
        if (seg.value == null) continue
        totalsByType[seg.key] = (totalsByType[seg.key] || 0) + seg.value
        grandTotal += seg.value
      }
    }
  }

  return (
    <Card>
      <div className="text-[10px] font-semibold uppercase tracking-wider text-gray-500 dark:text-gray-400 mb-3">
        Por tipo
      </div>
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-2">
        {TYPE_ORDER.map(key => {
          const value = totalsByType[key] || 0
          const pct = grandTotal > 0 ? value / grandTotal : 0
          const isSynthetic = key === 'OPTION_PREMIUM'
          const off = isSynthetic && !includeSynthetic

          return (
            <div
              key={key}
              data-testid={`type-chip-${key}`}
              data-off={off ? 'true' : 'false'}
              className={`px-3 py-2 rounded-lg border ${
                off
                  ? 'bg-gray-50 dark:bg-gray-900 border-dashed border-gray-300 dark:border-gray-700 opacity-60'
                  : 'bg-gray-50 dark:bg-gray-800/40 border-gray-200 dark:border-gray-800'
              }`}
            >
              <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-gray-500 flex-wrap">
                <span
                  className="w-1.5 h-1.5 rounded-full shrink-0"
                  style={{ background: TYPE_COLOR[key] }}
                />
                <span className="truncate">{TYPE_LABEL[key]}</span>
                {isSynthetic && (
                  <span className="inline-flex items-center px-1 py-px rounded text-[8px] font-semibold bg-purple-500/15 text-purple-600 dark:text-purple-300">
                    OPÇÕES
                  </span>
                )}
              </div>
              <div className="mt-1 text-sm font-semibold tnum">
                {loading ? '…' : fmtChart(value, currency, true)}
              </div>
              <div className="text-[10px] text-gray-500 tnum">
                {off ? 'desligado' : grandTotal > 0 ? fmtPct(pct, 0) : '—'}
              </div>
            </div>
          )
        })}
      </div>
    </Card>
  )
}
