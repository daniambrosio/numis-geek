/* Spec 81 — aba "Lançamentos": tabela completa (movida 1:1 do shell). */
import { MoreHorizontal, Plus } from 'lucide-react'

import type { AssetMovementOut } from '../../lib/api'
import { fmtDate, fmtNum } from '../../lib/format'
import { fmtMoney } from '../../lib/money'
import { Card, SectionTitle } from '../ui'

const TYPE_MOVEMENT_PALETTE: Record<string, string> = {
  BUY: 'bg-emerald-500/15 text-emerald-500 dark:text-emerald-400',
  SELL: 'bg-red-500/15 text-red-500 dark:text-red-400',
  BONUS: 'bg-indigo-500/15 text-indigo-500 dark:text-indigo-400',
  SUBSCRIPTION: 'bg-blue-500/15 text-blue-500 dark:text-blue-400',
  COME_COTAS: 'bg-orange-500/15 text-orange-500 dark:text-orange-400',
  FULL_REDEMPTION: 'bg-rose-500/15 text-rose-500 dark:text-rose-400',
  SELL_OPEN: 'bg-purple-500/15 text-purple-500 dark:text-purple-400',
  BUY_TO_OPEN: 'bg-purple-500/15 text-purple-500 dark:text-purple-400',
  BUY_TO_CLOSE: 'bg-purple-500/15 text-purple-500 dark:text-purple-400',
  SELL_TO_CLOSE: 'bg-purple-500/15 text-purple-500 dark:text-purple-400',
  EXERCISED: 'bg-amber-500/15 text-amber-500 dark:text-amber-400',
  EXPIRED: 'bg-gray-500/15 text-gray-500 dark:text-gray-400',
}

interface Props {
  movements: AssetMovementOut[]
  onRowClick: (m: AssetMovementOut) => void
  onNew: () => void
}

export default function AssetMovementsTab({ movements, onRowClick, onNew }: Props) {
  return (
    <div className="space-y-6" data-testid="asset-tab-panel-movements">
      <Card>
        <SectionTitle action={
          <button
            onClick={onNew}
            className="h-7 px-2.5 inline-flex items-center gap-1 rounded-md text-[11px] font-medium bg-indigo-500 hover:bg-indigo-400 text-white transition-colors"
          >
            <Plus className="w-3 h-3" /> Novo lançamento
          </button>
        }>
          Lançamentos · {movements.length}
        </SectionTitle>
        {movements.length === 0 ? (
          <div className="text-[12px] text-gray-500 italic py-6 text-center">Sem lançamentos cadastrados.</div>
        ) : (
          <div className="overflow-x-auto -mx-1">
            <table className="w-full text-[12px]">
              <thead>
                <tr className="text-[10px] uppercase tracking-wider text-gray-500">
                  <th className="text-left font-medium px-2 py-2">Data</th>
                  <th className="text-left font-medium px-2 py-2">Tipo</th>
                  <th className="text-right font-medium px-2 py-2">Qtd</th>
                  <th className="text-right font-medium px-2 py-2">Preço unitário</th>
                  <th className="text-right font-medium px-2 py-2">Taxa</th>
                  <th className="text-right font-medium px-2 py-2">Líquido</th>
                  <th className="px-2"></th>
                </tr>
              </thead>
              <tbody>
                {movements.map(m => {
                  const typeCls = TYPE_MOVEMENT_PALETTE[m.type] || 'bg-gray-500/15 text-gray-500'
                  return (
                    <tr
                      key={m.id}
                      onClick={() => onRowClick(m)}
                      className="border-t border-gray-100 dark:border-gray-800 hover:bg-gray-50 dark:hover:bg-gray-800/30 transition-colors cursor-pointer"
                    >
                      <td className="px-2 py-2 tnum text-gray-400">{fmtDate(m.event_date)}</td>
                      <td className="px-2">
                        <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] uppercase tracking-wider ${typeCls}`}>
                          {m.type_label}
                        </span>
                      </td>
                      <td className="px-2 text-right tnum">
                        {m.quantity != null
                          ? (m.quantity < 1 ? m.quantity.toFixed(4) : fmtNum(m.quantity, m.quantity < 100 ? 2 : 0))
                          : '—'}
                      </td>
                      <td className="px-2 text-right tnum money text-gray-400">{m.unit_price != null ? fmtMoney(m.unit_price, m.currency) : '—'}</td>
                      <td className="px-2 text-right tnum money text-gray-500">{m.fee ? fmtMoney(m.fee, m.currency) : '—'}</td>
                      <td className="px-2 text-right">
                        <div className={`tnum money font-medium ${m.net_amount < 0 ? 'text-red-500 dark:text-red-400' : m.net_amount > 0 ? 'text-emerald-500 dark:text-emerald-400' : 'text-gray-500'}`}>
                          {fmtMoney(m.net_amount, m.currency, { sign: true })}
                        </div>
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
    </div>
  )
}
