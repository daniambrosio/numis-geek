/**
 * Spec 61c — Suggested trades table: per asset, current vs target weight
 * and the trade value to reach the optimum. Sorted by |Δ| descending so
 * the largest rebalance moves bubble to the top.
 */
import type { OptimalAllocationOut } from '../lib/api'
import { KLASS, type CollapsedClassCode } from '../lib/tokens'

interface Props {
  allocations: OptimalAllocationOut[]
}

function fmtBRL(n: number): string {
  const sign = n < 0 ? '−' : (n > 0 ? '+' : '')
  const abs = Math.abs(n)
  return sign + new Intl.NumberFormat('pt-BR', {
    style: 'currency', currency: 'BRL',
    minimumFractionDigits: 0, maximumFractionDigits: 0,
  }).format(abs).replace('R$', 'R$ ')
}

function fmtPct(n: number): string {
  return `${(n * 100).toFixed(1)}%`
}

function flagOf(country: string): string {
  if (country === 'BR') return '🇧🇷'
  if (country === 'US') return '🇺🇸'
  return '🌐'
}

const ACTION_BADGE: Record<string, string> = {
  BUY: 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300',
  SELL: 'bg-red-500/15 text-red-700 dark:text-red-300',
  HOLD: 'bg-gray-500/15 text-gray-700 dark:text-gray-300',
}

const ACTION_LABEL: Record<string, string> = {
  BUY: 'Comprar', SELL: 'Vender', HOLD: 'Manter',
}

export default function SuggestedTradesTable({ allocations }: Props) {
  const sorted = [...allocations].sort(
    (a, b) => Math.abs(b.delta) - Math.abs(a.delta),
  )
  if (sorted.length === 0) {
    return (
      <div className="text-[12px] text-gray-500 italic py-4 text-center">
        Nenhum ativo elegível pra otimização.
      </div>
    )
  }
  return (
    <table data-testid="trades-table" className="w-full text-[12px]">
      <thead>
        <tr className="border-b border-gray-200 dark:border-gray-800 text-[10px] uppercase tracking-wider text-gray-500 dark:text-gray-400">
          <th className="text-left py-1.5 font-medium">Ativo</th>
          <th className="text-left py-1.5 font-medium">Classe</th>
          <th className="text-right py-1.5 font-medium">Atual</th>
          <th className="text-right py-1.5 font-medium">Alvo</th>
          <th className="text-right py-1.5 font-medium">Δ valor</th>
          <th className="text-right py-1.5 font-medium pr-1">Ação</th>
        </tr>
      </thead>
      <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
        {sorted.map((o) => {
          const klassToken = KLASS[o.asset_class as CollapsedClassCode]
          return (
            <tr key={o.asset_id} className="hover:bg-gray-50 dark:hover:bg-gray-800/40">
              <td className="py-1.5">
                <div className="flex items-center gap-1.5">
                  <span className="text-[11px] leading-none">{flagOf(o.country)}</span>
                  <span className="font-medium text-gray-900 dark:text-white">
                    {o.ticker || o.name}
                  </span>
                </div>
              </td>
              <td className="py-1.5">
                <span className="inline-flex items-center gap-1 text-[11px] text-gray-600 dark:text-gray-400">
                  <span
                    className="inline-block w-2 h-2 rounded-full"
                    style={{ background: klassToken?.color || '#9ca3af' }}
                  />
                  {klassToken?.label || o.asset_class}
                </span>
              </td>
              <td className="py-1.5 text-right tnum text-gray-700 dark:text-gray-300">
                {fmtPct(o.current_weight)}
              </td>
              <td className="py-1.5 text-right tnum text-gray-900 dark:text-white font-medium">
                {fmtPct(o.weight)}
              </td>
              <td className="py-1.5 text-right tnum text-gray-700 dark:text-gray-300">
                {fmtBRL(o.trade_value_brl)}
              </td>
              <td className="py-1.5 text-right pr-1">
                <span className={`inline-flex items-center px-1.5 py-0.5 rounded-full text-[10px] font-semibold ${ACTION_BADGE[o.trade_action] || ACTION_BADGE.HOLD}`}>
                  {ACTION_LABEL[o.trade_action] || o.trade_action}
                </span>
              </td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}
