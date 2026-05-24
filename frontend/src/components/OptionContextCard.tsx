import { Link } from 'react-router-dom'
import { ArrowUpRight, CircleDot } from 'lucide-react'

import type { AssetOut, PositionOut } from '../lib/api'
import { KLASS, type CollapsedClassCode } from '../lib/tokens'
import { TIER_COLOR, formatRelative, SOURCE_LABEL } from '../lib/price'
import {
  daysToExpiration, distanceToStrike, effectivePrice, isITM,
} from '../lib/option'

interface Props {
  /** The OPTION asset whose context we're rendering. */
  option: AssetOut
  /** Already-fetched underlying asset. */
  underlying: AssetOut
  /** Position of the OPTION asset — used for premium/share (average_cost). */
  position?: PositionOut | null
  /** Override "today" for tests. */
  now?: Date
}

function fmtPct(n: number, dp = 2): string {
  return new Intl.NumberFormat('pt-BR', {
    style: 'percent',
    minimumFractionDigits: dp,
    maximumFractionDigits: dp,
  }).format(n)
}

function fmtMoney(n: number, ccy: 'BRL' | 'USD'): string {
  return new Intl.NumberFormat('pt-BR', {
    style: 'currency',
    currency: ccy,
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(n)
}

function fmtDate(iso: string): string {
  return new Date(iso).toLocaleDateString('pt-BR')
}

export default function OptionContextCard({
  option, underlying, position, now,
}: Props) {
  // Render gate — defensive. Parent should already check, but keep the
  // component safe to drop in unconditionally.
  if (option.asset_class !== 'OPTION' || !option.underlying_id) return null
  if (!option.option_type || option.strike_price == null) return null
  if (!option.expiration_date) return null

  const strike = option.strike_price
  const optionType = option.option_type
  const currentPrice = underlying.current_price ?? 0
  const premiumPerShare = position?.average_cost
    ? Math.abs(Number(position.average_cost))
    : 0

  const itm = isITM(optionType, strike, currentPrice)
  const dist = distanceToStrike(strike, currentPrice)
  const days = daysToExpiration(option.expiration_date, now)
  const eff = effectivePrice(optionType, strike, premiumPerShare)

  const verdictLabel = itm ? 'Provável exercício' : 'Provável virar pó'
  const verdictColor = itm
    ? 'text-amber-500 dark:text-amber-400'
    : 'text-emerald-500 dark:text-emerald-400'

  const uKlass = (underlying.asset_class as CollapsedClassCode) in KLASS
    ? (underlying.asset_class as CollapsedClassCode)
    : 'OPTION'
  const uColor = KLASS[uKlass]?.color ?? '#94a3b8'
  const dotColor = TIER_COLOR[underlying.price_tier]
  const ageStr = formatRelative(underlying.price_updated_at, now)
  const sourceText = underlying.price_source
    ? `${SOURCE_LABEL[underlying.price_source]} · ${ageStr}`
    : ageStr

  const ccy = (underlying.currency ?? 'BRL') as 'BRL' | 'USD'
  const optCcy = (option.currency ?? 'BRL') as 'BRL' | 'USD'

  return (
    <div className="rounded-xl overflow-hidden bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800">
      {/* Header */}
      <div className="px-5 py-4 border-b border-gray-200 dark:border-gray-800 bg-gradient-to-br from-indigo-500/5 via-purple-500/5 to-transparent">
        <div className="flex items-center gap-2 text-[10px] uppercase tracking-wider text-gray-500 font-semibold">
          <span
            className="w-1.5 h-1.5 rounded-full"
            style={{ background: KLASS.OPTION.color }}
          />
          Ativo subjacente
        </div>
        <div className="mt-2 flex items-center gap-4 flex-wrap">
          <Link
            to={`/assets/${underlying.id}`}
            className="group inline-flex items-center gap-2 hover:opacity-90 transition-opacity"
          >
            <span
              className="w-1 h-7 rounded-full"
              style={{ background: uColor }}
            />
            <span className="text-xl font-mono font-semibold group-hover:text-indigo-500 dark:group-hover:text-indigo-300 transition-colors">
              {underlying.ticker ?? underlying.name}
            </span>
            <ArrowUpRight
              className="w-3.5 h-3.5 text-gray-400 group-hover:text-indigo-500 dark:group-hover:text-indigo-300 transition-colors"
            />
          </Link>
          <span className="text-gray-300 dark:text-gray-700">│</span>
          <div className="flex items-center gap-2">
            <span className="text-2xl font-semibold tnum">
              {underlying.current_price != null
                ? fmtMoney(currentPrice, ccy)
                : '—'}
            </span>
            <span
              className="w-1.5 h-1.5 rounded-full"
              style={{ background: dotColor }}
              title={sourceText}
            />
            <span className="text-[11px] text-gray-500 tnum">{ageStr}</span>
          </div>
        </div>
      </div>

      {/* 4 tiles */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 p-4">
        <div className="px-4 py-3 rounded-xl bg-gray-50 dark:bg-gray-800/40 border border-gray-200 dark:border-gray-800">
          <div className="text-[10px] uppercase tracking-wider font-medium text-gray-500">
            Strike
          </div>
          <div className="mt-1 text-lg font-semibold tnum">
            {fmtMoney(strike, optCcy)}
          </div>
          <div className="text-[11px] text-gray-500 mt-0.5">
            {optionType === 'PUT'
              ? 'Comprador exerce vendendo'
              : 'Comprador exerce comprando'}
          </div>
        </div>

        <div className="px-4 py-3 rounded-xl bg-gray-50 dark:bg-gray-800/40 border border-gray-200 dark:border-gray-800">
          <div className="text-[10px] uppercase tracking-wider font-medium text-gray-500">
            Distância p/ strike
          </div>
          <div
            className={`mt-1 text-lg font-semibold tnum ${
              dist >= 0
                ? 'text-emerald-500 dark:text-emerald-400'
                : 'text-red-500 dark:text-red-400'
            }`}
          >
            {dist >= 0 ? '+' : ''}{fmtPct(dist)}
          </div>
          <div className="text-[11px] mt-0.5">
            <span
              className={`inline-flex items-center px-1.5 py-0.5 rounded text-[9px] font-semibold uppercase tracking-wider ${
                itm
                  ? 'bg-amber-500/15 text-amber-600 dark:text-amber-400'
                  : 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400'
              }`}
              data-testid="itm-badge"
            >
              {itm ? 'ITM' : 'OTM'}
            </span>
            <span className="text-gray-500 ml-1.5">
              {itm ? 'in-the-money' : 'out-of-the-money'}
            </span>
          </div>
        </div>

        <div className="px-4 py-3 rounded-xl bg-gray-50 dark:bg-gray-800/40 border border-gray-200 dark:border-gray-800">
          <div className="text-[10px] uppercase tracking-wider font-medium text-gray-500">
            Vence em
          </div>
          <div
            className={`mt-1 text-lg font-semibold tnum ${
              days < 14 ? 'text-amber-500 dark:text-amber-400' : ''
            }`}
          >
            {days} dias
          </div>
          <div className="text-[11px] text-gray-500 mt-0.5">
            {fmtDate(option.expiration_date)}
          </div>
        </div>

        <div className="px-4 py-3 rounded-xl bg-gray-50 dark:bg-gray-800/40 border border-gray-200 dark:border-gray-800">
          <div className="text-[10px] uppercase tracking-wider font-medium text-gray-500">
            Cenário provável
          </div>
          <div className={`mt-1 text-sm font-semibold ${verdictColor}`}>
            {verdictLabel}
          </div>
          <div className="text-[11px] text-gray-500 mt-0.5">
            se exercida:{' '}
            <span className="tnum text-gray-700 dark:text-gray-300">
              {fmtMoney(eff, optCcy)}
            </span>
          </div>
        </div>
      </div>

      {/* Footer */}
      <div className="px-5 py-3 border-t border-gray-200 dark:border-gray-800 text-[11px] text-gray-500 flex items-center justify-between flex-wrap gap-2">
        <span className="inline-flex items-center gap-1">
          <CircleDot className="w-3 h-3 text-indigo-400" />
          Prêmio recebido conta como{' '}
          <span className="font-medium text-gray-700 dark:text-gray-300">
            Dividendo sintético
          </span>{' '}
          em /proventos, separado do {underlying.ticker ?? underlying.name}.
        </span>
        <Link
          to={`/assets/${underlying.id}`}
          className="text-indigo-500 dark:text-indigo-400 hover:underline whitespace-nowrap"
        >
          Ver {underlying.ticker ?? underlying.name} →
        </Link>
      </div>
    </div>
  )
}
