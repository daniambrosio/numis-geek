/* Spec 81 — aba "Proventos": tabela completa + gráfico mensal (spec 50). */
import { MoreHorizontal, Plus } from 'lucide-react'

import type { DistributionOut } from '../../lib/api'
import { fmtDate } from '../../lib/format'
import { fmtBRL, fmtMoney, fmtUSD } from '../../lib/money'
import AssetDistributionsChart from '../AssetDistributionsChart'
import { Card, SectionTitle } from '../ui'

const TYPE_DISTRIBUTION_PALETTE: Record<string, string> = {
  DIVIDEND: 'bg-amber-500/15 text-amber-500 dark:text-amber-400',
  INTEREST: 'bg-cyan-500/15 text-cyan-500 dark:text-cyan-400',
  JCP: 'bg-emerald-500/15 text-emerald-500 dark:text-emerald-400',
  SECURITIES_LENDING: 'bg-orange-500/15 text-orange-500 dark:text-orange-400',
}

interface Props {
  distributions: DistributionOut[]
  totalBRL: number
  totalUSD: number
  onRowClick?: (d: DistributionOut) => void
  onNew?: () => void
}

export default function AssetDistributionsTab({
  distributions, totalBRL, totalUSD, onRowClick, onNew,
}: Props) {
  return (
    <div className="space-y-6" data-testid="asset-tab-panel-distributions">
      <Card>
        <SectionTitle action={
          <div className="flex items-center gap-3">
            <span className="text-[11px] tnum text-gray-500">
              Total{' '}
              <span className="money text-emerald-500 dark:text-emerald-400 font-medium">
                {fmtBRL(totalBRL, { compact: true })}
              </span>
              <span className="mx-1 text-gray-400">·</span>
              <span className="money text-emerald-500 dark:text-emerald-400 font-medium">
                {fmtUSD(totalUSD, { compact: true })}
              </span>
            </span>
            {onNew && (
              <button
                onClick={onNew}
                className="h-7 px-2.5 inline-flex items-center gap-1 rounded-md text-[11px] font-medium bg-indigo-500 hover:bg-indigo-400 text-white transition-colors"
              >
                <Plus className="w-3 h-3" /> Novo provento
              </button>
            )}
          </div>
        }>
          Proventos · {distributions.length}
        </SectionTitle>
        {distributions.length === 0 ? (
          <div className="text-[12px] text-gray-500 italic py-6 text-center">Sem proventos cadastrados.</div>
        ) : (
          <div className="overflow-x-auto -mx-1">
            <table className="w-full text-[12px]">
              <thead>
                <tr className="text-[10px] uppercase tracking-wider text-gray-500">
                  <th className="text-left font-medium px-2 py-2">Data</th>
                  <th className="text-left font-medium px-2 py-2">Tipo</th>
                  <th className="text-right font-medium px-2 py-2">Bruto</th>
                  <th className="text-right font-medium px-2 py-2">IR</th>
                  <th className="text-right font-medium px-2 py-2">Líquido</th>
                  <th className="text-right font-medium px-2 py-2">USD</th>
                  <th className="px-2"></th>
                </tr>
              </thead>
              <tbody>
                {distributions.map(d => {
                  const typeCls = TYPE_DISTRIBUTION_PALETTE[d.type] || 'bg-gray-500/15 text-gray-500'
                  const fx = d.fx_rate || 0
                  const usdNet = d.currency === 'USD'
                    ? d.net_amount
                    : (fx > 0 ? d.net_amount / fx : null)
                  return (
                    <tr
                      key={d.id}
                      onClick={onRowClick ? () => onRowClick(d) : undefined}
                      data-testid={`distribution-row-${d.id}`}
                      className={`border-t border-gray-100 dark:border-gray-800 hover:bg-gray-50 dark:hover:bg-gray-800/30 transition-colors ${onRowClick ? 'cursor-pointer' : ''}`}
                    >
                      <td className="px-2 py-2 tnum text-gray-400">{fmtDate(d.event_date)}</td>
                      <td className="px-2">
                        <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] uppercase tracking-wider ${typeCls}`}>
                          {d.type_label}
                        </span>
                      </td>
                      <td className="px-2 text-right tnum money text-gray-400">{fmtMoney(d.gross_amount, d.currency)}</td>
                      <td className="px-2 text-right tnum money text-amber-500 dark:text-amber-400">{d.tax && d.tax > 0 ? '−' + fmtMoney(d.tax, d.currency) : '—'}</td>
                      <td className="px-2 text-right">
                        <div className="tnum money font-medium text-emerald-500 dark:text-emerald-400">{fmtMoney(d.net_amount, d.currency, { sign: true })}</div>
                      </td>
                      <td className="px-2 text-right tnum money text-gray-500 dark:text-gray-400" title={fx > 0 ? `PTAX ${fx.toFixed(4)}` : 'sem fx_rate'}>
                        {usdNet == null ? '—' : fmtUSD(usdNet)}
                      </td>
                      <td className="px-2 text-gray-500"><MoreHorizontal className="w-4 h-4" /></td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {distributions.length >= 2 && (
        <AssetDistributionsChart distributions={distributions} />
      )}
    </div>
  )
}
