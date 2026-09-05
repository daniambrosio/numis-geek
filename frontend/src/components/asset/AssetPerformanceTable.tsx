/* Spec 81 — tabela "resultado por fechamento": uma linha por fechamento
 * CLOSED com valor, investido, P&L, proventos do mês e retorno do mês. */
import { Link } from 'react-router-dom'

import type { AssetPerformanceRow } from '../../lib/api'
import { fmtPct } from '../../lib/format'
import { fmtBRL, fmtMoney, fmtUSD } from '../../lib/money'
import { Card, SectionTitle } from '../ui'

const PT_MONTHS = ['Jan', 'Fev', 'Mar', 'Abr', 'Mai', 'Jun', 'Jul', 'Ago', 'Set', 'Out', 'Nov', 'Dez']

function fmtPeriod(iso: string): string {
  const [y, m] = iso.split('-')
  return `${PT_MONTHS[parseInt(m, 10) - 1] ?? m}/${y.slice(2)}`
}

function fmtQty(n: number): string {
  return n.toLocaleString('pt-BR', {
    minimumFractionDigits: n < 1 ? 4 : 0,
    maximumFractionDigits: n < 1 ? 6 : 4,
  })
}

const NULL_REASON_PT: Record<string, string> = {
  FIRST_CLOSING: 'primeiro fechamento do ativo',
  GAP: 'ativo ausente no fechamento anterior',
  ZERO_START: 'valor zerado no fechamento anterior',
  MISSING_MV: 'fechamento sem valor de mercado gravado',
  OPTION: 'opção — retorno não se aplica',
}

function num(x: string | null | undefined): number | null {
  return x == null ? null : Number(x)
}

function pctCls(v: number | null): string {
  if (v == null) return 'text-gray-400'
  if (v > 0) return 'text-emerald-600 dark:text-emerald-400'
  if (v < 0) return 'text-red-600 dark:text-red-400'
  return 'text-gray-500'
}

interface Props {
  /** Linhas em ordem cronológica DESC (como vêm da API). */
  rows: AssetPerformanceRow[]
  currency: string
  isValueMode: boolean
  assetId: string
}

export default function AssetPerformanceTable({ rows, currency, isValueMode, assetId }: Props) {
  return (
    <Card padding="p-5">
      <div className="flex items-center justify-between mb-3">
        <SectionTitle>Resultado por fechamento</SectionTitle>
        <span className="text-[10px] text-gray-500">
          {rows.length} fechamento{rows.length === 1 ? '' : 's'} · apenas confirmados
        </span>
      </div>
      {rows.length === 0 ? (
        <div className="text-[12px] text-gray-400 py-4 text-center">
          Sem fechamentos ainda — o ativo aparecerá aqui depois que o primeiro
          snapshot mensal for confirmado.
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-[12px]" data-testid="asset-performance-table">
            <thead>
              <tr className="text-[10px] uppercase tracking-wider text-gray-500 border-b border-gray-200 dark:border-gray-800">
                <th className="text-left font-medium py-2 px-2">Período</th>
                <th className="text-right font-medium py-2 px-2">Qtd</th>
                <th className="text-right font-medium py-2 px-2">Preço unitário</th>
                <th className="text-right font-medium py-2 px-2">Valor total (BRL)</th>
                <th className="text-right font-medium py-2 px-2">Valor total (USD)</th>
                <th className="text-right font-medium py-2 px-2">Investido</th>
                <th className="text-right font-medium py-2 px-2">P&L</th>
                <th className="text-right font-medium py-2 px-2">Proventos no mês</th>
                <th className="text-right font-medium py-2 px-2">Retorno no mês</th>
                <th className="text-right font-medium py-2 px-2">Δ MoM</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, idx) => {
                const ym = r.period_end_date.slice(0, 7)
                const qty = Number(r.quantity)
                const unit = num(r.unit_price)
                const mvBrl = num(r.market_value_brl)
                const mvUsd = num(r.market_value_usd)
                const invested = num(r.total_invested_brl)
                const pnl = num(r.pnl_brl)
                const provNative = Number(r.proventos_native)
                const provBrl = Number(r.proventos_brl)
                // rows[idx + 1] é o mês cronologicamente anterior (lista desc).
                const prevMv = num(rows[idx + 1]?.market_value_brl)
                const delta = mvBrl != null && prevMv != null && prevMv > 0 ? (mvBrl - prevMv) / prevMv : null
                return (
                  <tr
                    key={r.period_end_date}
                    className="border-b border-gray-100 dark:border-gray-800/60 hover:bg-gray-50 dark:hover:bg-gray-800/40"
                    data-testid="asset-performance-row"
                  >
                    <td className="py-2 px-2">
                      <Link
                        to={`/snapshots/${ym}`}
                        state={{ from: `/assets/${assetId}?tab=performance`, fromLabel: 'ativo' }}
                        className="text-indigo-500 hover:text-indigo-300"
                      >
                        {fmtPeriod(r.period_end_date)}
                      </Link>
                    </td>
                    <td className="py-2 px-2 text-right tnum text-gray-700 dark:text-gray-300">
                      {isValueMode || qty === 0 ? '—' : fmtQty(qty)}
                    </td>
                    <td className="py-2 px-2 text-right tnum text-gray-700 dark:text-gray-300">
                      {isValueMode || unit == null ? '—' : fmtMoney(unit, currency)}
                    </td>
                    <td className="py-2 px-2 text-right tnum text-gray-700 dark:text-gray-300">{fmtBRL(mvBrl)}</td>
                    <td className="py-2 px-2 text-right tnum text-gray-500 dark:text-gray-400">{fmtUSD(mvUsd)}</td>
                    <td className="py-2 px-2 text-right tnum text-gray-500 dark:text-gray-400">{fmtBRL(invested)}</td>
                    <td className={`py-2 px-2 text-right tnum ${pctCls(pnl)}`}>
                      {pnl == null ? '—' : (
                        <>
                          <div>{fmtBRL(pnl, { sign: true, compact: true })}</div>
                          <div className="text-[10px] opacity-80">{fmtPct(r.pnl_pct, 1, true)}</div>
                        </>
                      )}
                    </td>
                    <td className="py-2 px-2 text-right tnum text-emerald-600 dark:text-emerald-400">
                      {provNative === 0 ? <span className="text-gray-400">—</span> : (
                        <>
                          <div>{fmtMoney(provNative, currency)}</div>
                          {currency !== 'BRL' && <div className="text-[10px] text-gray-500">{fmtBRL(provBrl)}</div>}
                        </>
                      )}
                    </td>
                    <td
                      className={`py-2 px-2 text-right tnum font-medium ${pctCls(r.return_pct)}`}
                      title={r.return_pct == null && r.return_null_reason ? NULL_REASON_PT[r.return_null_reason] ?? r.return_null_reason : undefined}
                      data-testid="asset-performance-return"
                    >
                      {r.return_pct == null ? '—' : fmtPct(r.return_pct, 2, true)}
                      {currency !== 'BRL' && r.return_brl_pct != null && (
                        <div className="text-[10px] text-gray-500 font-normal">{fmtPct(r.return_brl_pct, 2, true)} em BRL</div>
                      )}
                    </td>
                    <td className={`py-2 px-2 text-right tnum ${pctCls(delta)}`}>
                      {delta == null ? '—' : fmtPct(delta, 2, true)}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  )
}
