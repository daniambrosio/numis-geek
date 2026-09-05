/* Spec 81 — aba "Proventos": tabela completa (reais + prêmios sintéticos de
 * opção, spec 32) e gráfico mensal (spec 50). Linha real abre o painel de
 * detalhe; sintética não é editável aqui (vem de um lançamento de opção). */
import { useMemo } from 'react'
import { MoreHorizontal, Plus } from 'lucide-react'

import type { DistributionOut, SyntheticPremiumOut } from '../../lib/api'
import { fmtDate } from '../../lib/format'
import { fmtBRL, fmtMoney, fmtUSD } from '../../lib/money'
import AssetDistributionsChart from '../AssetDistributionsChart'
import { Card, SectionTitle } from '../ui'

const TYPE_DISTRIBUTION_PALETTE: Record<string, string> = {
  DIVIDEND: 'bg-amber-500/15 text-amber-500 dark:text-amber-400',
  INTEREST: 'bg-cyan-500/15 text-cyan-500 dark:text-cyan-400',
  JCP: 'bg-emerald-500/15 text-emerald-500 dark:text-emerald-400',
  SECURITIES_LENDING: 'bg-orange-500/15 text-orange-500 dark:text-orange-400',
  OPTION_PREMIUM: 'bg-purple-500/15 text-purple-500 dark:text-purple-400',
}

type Row =
  | { kind: 'real'; id: string; date: string; d: DistributionOut }
  | { kind: 'synthetic'; id: string; date: string; p: SyntheticPremiumOut }

/** Totais em BRL e USD de uma lista de linhas (reais + sintéticas). fx_rate é
 *  multiplicador pra BRL (linha BRL tem fx=1). */
export function sumDistributions(
  distributions: DistributionOut[], premiums: SyntheticPremiumOut[],
): { brl: number; usd: number } {
  let brl = 0
  let usd = 0
  const add = (net: number, currency: string, fx: number | null | undefined) => {
    const rate = fx || 0
    if (currency === 'USD') {
      usd += net
      brl += rate > 0 ? net * rate : 0
    } else {
      brl += net
      usd += rate > 0 ? net / rate : 0
    }
  }
  for (const d of distributions) add(d.net_amount, d.currency, d.fx_rate)
  for (const p of premiums) add(p.net_amount, p.currency, p.fx_rate)
  return { brl, usd }
}

interface Props {
  distributions: DistributionOut[]
  syntheticPremiums: SyntheticPremiumOut[]
  onRowClick: (d: DistributionOut) => void
  onNew: () => void
}

export default function AssetDistributionsTab({
  distributions, syntheticPremiums, onRowClick, onNew,
}: Props) {
  const rows = useMemo<Row[]>(() => {
    const out: Row[] = [
      ...distributions.map(d => ({ kind: 'real' as const, id: d.id, date: d.event_date, d })),
      ...syntheticPremiums.map(p => ({ kind: 'synthetic' as const, id: p.id, date: p.event_date, p })),
    ]
    return out.sort((a, b) => b.date.localeCompare(a.date))
  }, [distributions, syntheticPremiums])
  const totals = useMemo(() => sumDistributions(distributions, syntheticPremiums), [distributions, syntheticPremiums])

  return (
    <div className="space-y-6" data-testid="asset-tab-panel-distributions">
      <Card>
        <SectionTitle action={
          <div className="flex items-center gap-3">
            <span className="text-[11px] tnum text-gray-500" data-testid="distributions-total">
              Total{' '}
              <span className="money text-emerald-500 dark:text-emerald-400 font-medium">
                {fmtBRL(totals.brl, { compact: true })}
              </span>
              <span className="mx-1 text-gray-400">·</span>
              <span className="money text-emerald-500 dark:text-emerald-400 font-medium">
                {fmtUSD(totals.usd, { compact: true })}
              </span>
              {syntheticPremiums.length > 0 && (
                <span className="ml-1 text-gray-400">incl. prêmios</span>
              )}
            </span>
            <button
              onClick={onNew}
              data-testid="distributions-new"
              className="h-7 px-2.5 inline-flex items-center gap-1 rounded-md text-[11px] font-medium bg-indigo-500 hover:bg-indigo-400 text-white transition-colors"
            >
              <Plus className="w-3 h-3" /> Novo provento
            </button>
          </div>
        }>
          Proventos · {rows.length}
        </SectionTitle>
        {rows.length === 0 ? (
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
                {rows.map(row => {
                  if (row.kind === 'synthetic') {
                    const p = row.p
                    const fx = p.fx_rate || 0
                    const usdNet = p.currency === 'USD' ? p.net_amount : (fx > 0 ? p.net_amount / fx : null)
                    return (
                      <tr
                        key={row.id}
                        data-testid={`premium-row-${p.movement_id}`}
                        title={`Prêmio de ${p.option_ticker ?? 'opção'} (${p.side === 'SELL_OPEN' ? 'venda' : 'recompra'}) — edite pelo lançamento da opção`}
                        className="border-t border-gray-100 dark:border-gray-800 opacity-90"
                      >
                        <td className="px-2 py-2 tnum text-gray-400">{fmtDate(p.event_date)}</td>
                        <td className="px-2">
                          <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] uppercase tracking-wider ${TYPE_DISTRIBUTION_PALETTE.OPTION_PREMIUM}`}>
                            {p.type_label}
                          </span>
                          {p.option_ticker && (
                            <span className="ml-1.5 font-mono text-[10px] text-gray-500">{p.option_ticker}</span>
                          )}
                        </td>
                        <td className="px-2 text-right tnum money text-gray-400">{fmtMoney(p.gross_amount, p.currency)}</td>
                        <td className="px-2 text-right tnum money text-gray-400">—</td>
                        <td className="px-2 text-right">
                          <div className={`tnum money font-medium ${p.net_amount < 0 ? 'text-red-500 dark:text-red-400' : 'text-emerald-500 dark:text-emerald-400'}`}>
                            {fmtMoney(p.net_amount, p.currency, { sign: true })}
                          </div>
                        </td>
                        <td className="px-2 text-right tnum money text-gray-500 dark:text-gray-400">
                          {usdNet == null ? '—' : fmtUSD(usdNet)}
                        </td>
                        <td className="px-2"></td>
                      </tr>
                    )
                  }
                  const d = row.d
                  const typeCls = TYPE_DISTRIBUTION_PALETTE[d.type] || 'bg-gray-500/15 text-gray-500'
                  const fx = d.fx_rate || 0
                  const usdNet = d.currency === 'USD' ? d.net_amount : (fx > 0 ? d.net_amount / fx : null)
                  return (
                    <tr
                      key={row.id}
                      onClick={() => onRowClick(d)}
                      data-testid={`distribution-row-${d.id}`}
                      className="border-t border-gray-100 dark:border-gray-800 hover:bg-gray-50 dark:hover:bg-gray-800/30 transition-colors cursor-pointer"
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
