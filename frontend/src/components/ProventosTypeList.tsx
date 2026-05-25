/* Spec 33 — compact "Por tipo" list for the Dashboard Proventos card.
 *
 * Same data as <ProventosByTypeCard /> (spec 32) but rendered as a
 * vertical list of 5 rows, no Card wrapper (lives inside parent Card).
 * Click on a row navigates to /distributions?type=KEY. */
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import {
  api,
  type ChartCurrency,
  type ChartDataOut,
  type ChartPeriod,
} from '../lib/api'
import { fmtChart, fmtPct } from '../lib/chart'

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
  INTEREST:           'Juros',
  JCP:                'JCP',
  SECURITIES_LENDING: 'Aluguel',
  OPTION_PREMIUM:     'Prêmio sintético',
}

interface Props {
  includeSynthetic: boolean
  currency?: ChartCurrency
  period?: ChartPeriod
}

export default function ProventosTypeList({
  includeSynthetic, currency = 'BRL', period = '12m',
}: Props) {
  const navigate = useNavigate()
  const [data, setData] = useState<ChartDataOut | null>(null)
  const [loading, setLoading] = useState(true)

  // Always fetch with include_synthetic=true so OPTION_PREMIUM total is
  // available even when the dim state is on. The dim state is purely UI.
  useEffect(() => {
    setLoading(true)
    api.getDistributionsChart({
      period, breakdown: 'type', currency, include_synthetic: true,
    })
      .then(setData)
      .finally(() => setLoading(false))
  }, [period, currency])

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
    <div className="mt-3 pt-3 border-t border-gray-200 dark:border-gray-800">
      <div className="text-[10px] uppercase tracking-wider text-gray-500 dark:text-gray-400 font-medium mb-2">
        Por tipo
      </div>
      <div className="space-y-1">
        {TYPE_ORDER.map(key => {
          const value = totalsByType[key] || 0
          const pct = grandTotal > 0 ? value / grandTotal : 0
          const isSynthetic = key === 'OPTION_PREMIUM'
          const off = isSynthetic && !includeSynthetic

          return (
            <button
              key={key}
              type="button"
              data-testid={`type-row-${key}`}
              data-off={off ? 'true' : 'false'}
              onClick={() => navigate(`/distributions?type=${key}`)}
              className={`w-full flex items-center gap-2 text-[11px] px-1 py-0.5 -mx-1 rounded hover:bg-gray-100 dark:hover:bg-gray-800/40 transition-colors ${
                off ? 'opacity-50' : ''
              }`}
            >
              <span
                className="w-1.5 h-1.5 rounded-full shrink-0"
                style={{ background: TYPE_COLOR[key] }}
              />
              <span className="text-gray-700 dark:text-gray-300 flex items-center gap-1.5 min-w-0">
                <span className="truncate">{TYPE_LABEL[key]}</span>
                {isSynthetic && (
                  <span className="inline-flex items-center px-1 py-0 rounded text-[8px] font-semibold tracking-wider bg-purple-500/15 text-purple-600 dark:text-purple-300">
                    OPÇÕES
                  </span>
                )}
              </span>
              <div className="flex-1" />
              <span className="text-gray-500 dark:text-gray-400 tnum text-[10px]">
                {off ? 'desligado' : grandTotal > 0 ? fmtPct(pct, 0) : '—'}
              </span>
              <span className="tnum money font-medium text-gray-700 dark:text-gray-300 w-16 text-right">
                {loading ? '…' : fmtChart(value, currency, true)}
              </span>
            </button>
          )
        })}
      </div>
    </div>
  )
}
