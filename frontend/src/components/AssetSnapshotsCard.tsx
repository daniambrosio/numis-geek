/* Spec 50 — Asset Detail · Tabela + sparkline dos fechamentos do ativo.
 *
 * Renderiza um card embaixo dos KPIs em /assets/{id}. Cada linha vem de
 * um CLOSED PortfolioSnapshot onde o ativo tinha um item. Δ MoM é
 * calculado client-side comparando market_value_brl entre meses
 * adjacentes (a API já devolve ordenado desc). */
import { useMemo } from 'react'
import { Link } from 'react-router-dom'

import type { AssetSnapshotHistoryOut } from '../lib/api'
import Sparkline from './Sparkline'
import { Card, SectionTitle } from './ui'

interface Props {
  history: AssetSnapshotHistoryOut | null
  loading?: boolean
  assetId: string
}

function fmtBRL(n: number | null | undefined): string {
  if (n == null) return '—'
  return n.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })
}

function fmtUSD(n: number | null | undefined): string {
  if (n == null) return '—'
  return n.toLocaleString('en-US', { style: 'currency', currency: 'USD' })
}

function fmtQty(n: number): string {
  return n.toLocaleString('pt-BR', {
    minimumFractionDigits: n < 1 ? 4 : 0,
    maximumFractionDigits: n < 1 ? 6 : 4,
  })
}

function fmtPct(n: number, sign = true): string {
  const v = (n * 100).toFixed(2)
  return (sign && n > 0 ? '+' : '') + v + '%'
}

const PT_MONTHS = [
  'Jan', 'Fev', 'Mar', 'Abr', 'Mai', 'Jun',
  'Jul', 'Ago', 'Set', 'Out', 'Nov', 'Dez',
]

function fmtPeriod(iso: string): string {
  const [y, m] = iso.split('-')
  const month = PT_MONTHS[parseInt(m, 10) - 1] ?? m
  return `${month}/${y.slice(2)}`
}

function ymOf(iso: string): string {
  return iso.slice(0, 7)
}

export default function AssetSnapshotsCard({ history, loading, assetId }: Props) {
  // Items come desc; reverse for chronological asc for the chart.
  const ascPoints = useMemo(
    () =>
      [...(history?.items ?? [])]
        .reverse()
        .map(it => Number(it.market_value_brl ?? 0))
        .filter(v => v > 0),
    [history],
  )

  const rows = history?.items ?? []

  if (loading) {
    return (
      <Card padding="p-5">
        <SectionTitle>Fechamentos</SectionTitle>
        <div className="text-[12px] text-gray-400 py-4 text-center">
          Carregando…
        </div>
      </Card>
    )
  }

  if (!rows.length) {
    return (
      <Card padding="p-5">
        <SectionTitle>Fechamentos</SectionTitle>
        <div className="text-[12px] text-gray-400 py-4 text-center">
          Sem fechamentos ainda — o ativo aparecerá aqui depois que o
          primeiro snapshot mensal for confirmado.
        </div>
      </Card>
    )
  }

  return (
    <Card padding="p-5">
      <div className="flex items-center justify-between mb-3">
        <SectionTitle>Fechamentos</SectionTitle>
        <span className="text-[10px] text-gray-500">
          {rows.length} fechamento{rows.length === 1 ? '' : 's'} ·
          {' '}apenas confirmados
        </span>
      </div>

      {ascPoints.length >= 2 && (
        <div className="mb-4 -mx-1">
          <Sparkline data={ascPoints} h={80} color="#818cf8" filled />
        </div>
      )}

      <div className="overflow-x-auto">
        <table className="w-full text-[12px]" data-testid="asset-snapshots-table">
          <thead>
            <tr className="text-[10px] uppercase tracking-wider text-gray-500 border-b border-gray-200 dark:border-gray-800">
              <th className="text-left font-medium py-2 px-2">Período</th>
              <th className="text-right font-medium py-2 px-2">Qtd</th>
              <th className="text-right font-medium py-2 px-2">Preço fim</th>
              <th className="text-right font-medium py-2 px-2">Valor BRL</th>
              <th className="text-right font-medium py-2 px-2">Valor USD</th>
              <th className="text-right font-medium py-2 px-2">Δ MoM</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((it, idx) => {
              const ym = ymOf(it.period_end_date)
              const cur = it.market_value_brl != null ? Number(it.market_value_brl) : null
              // rows[idx + 1] is the chronologically previous month (desc list).
              const prev = rows[idx + 1]
              const prevVal = prev?.market_value_brl != null ? Number(prev.market_value_brl) : null
              const delta = cur != null && prevVal != null && prevVal > 0
                ? (cur - prevVal) / prevVal
                : null
              const deltaCls = delta == null
                ? 'text-gray-400'
                : delta > 0
                  ? 'text-emerald-600 dark:text-emerald-400'
                  : delta < 0
                    ? 'text-red-600 dark:text-red-400'
                    : 'text-gray-500'
              const qty = Number(it.quantity)
              const up = it.unit_price != null ? Number(it.unit_price) : null
              const usd = it.market_value_usd != null ? Number(it.market_value_usd) : null
              return (
                <tr
                  key={it.period_end_date}
                  className="border-b border-gray-100 dark:border-gray-800/60 hover:bg-gray-50 dark:hover:bg-gray-800/40"
                  data-testid="asset-snapshots-row"
                >
                  <td className="py-2 px-2">
                    <Link
                      to={`/snapshots/${ym}`}
                      state={{ from: `/assets/${assetId}`, fromLabel: 'ativo' }}
                      className="text-indigo-500 hover:text-indigo-300"
                    >
                      {fmtPeriod(it.period_end_date)}
                    </Link>
                  </td>
                  <td className="py-2 px-2 text-right tnum text-gray-700 dark:text-gray-300">
                    {qty === 0 ? '—' : fmtQty(qty)}
                  </td>
                  <td className="py-2 px-2 text-right tnum text-gray-700 dark:text-gray-300">
                    {up == null ? '—' : up.toLocaleString('pt-BR', {
                      style: 'currency',
                      currency: history?.currency ?? 'BRL',
                    })}
                  </td>
                  <td className="py-2 px-2 text-right tnum text-gray-700 dark:text-gray-300">
                    {fmtBRL(cur)}
                  </td>
                  <td className="py-2 px-2 text-right tnum text-gray-700 dark:text-gray-300">
                    {fmtUSD(usd)}
                  </td>
                  <td className={`py-2 px-2 text-right tnum ${deltaCls}`}>
                    {delta == null ? '—' : fmtPct(delta)}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </Card>
  )
}
