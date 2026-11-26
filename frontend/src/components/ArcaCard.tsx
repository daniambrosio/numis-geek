/* Spec 85 — card ARCA do Suporte à Decisão: atual × meta por letra (com
 * banda), subcategorias, renda 12m, ataque × defesa e simulador de aporte. */
import { useState } from 'react'
import { AlertTriangle, ChevronDown, ChevronRight } from 'lucide-react'

import {
  api,
  type ArcaLetterOut,
  type ArcaPlanOut,
  type ArcaStatus,
  type ArcaSummaryOut,
} from '../lib/api'
import {
  ARCA_LETTER_COLOR,
  ARCA_LETTER_LABEL,
  ARCA_LETTER_SHORT,
  ARCA_SUB_LABEL,
  parseAmount,
} from '../lib/arca'
import { fmtPct } from '../lib/format'
import { fmtBRL } from '../lib/money'
import { Card } from './ui'

const STATUS_LABEL: Record<ArcaStatus, string> = {
  IN_BAND: 'Na faixa',
  BELOW_BAND: 'Abaixo da faixa',
  ABOVE_BAND: 'Acima da faixa',
  NO_TARGET: 'Sem meta',
}

const STATUS_CLASS: Record<ArcaStatus, string> = {
  IN_BAND: 'bg-emerald-50 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300',
  BELOW_BAND: 'bg-amber-50 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300',
  ABOVE_BAND: 'bg-red-50 text-red-700 dark:bg-red-900/30 dark:text-red-300',
  NO_TARGET: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400',
}

function n(s: string | null | undefined): number {
  return s == null ? 0 : Number(s)
}

function LetterBar({ l }: { l: ArcaLetterOut }) {
  const cur = Math.min(l.current_pct, 1) * 100
  const lo = n(l.min_pct) * 100
  const hi = n(l.max_pct) * 100
  const tgt = l.target_pct != null ? n(l.target_pct) * 100 : null
  return (
    <div className="relative h-3 rounded-full bg-gray-100 dark:bg-gray-800 overflow-hidden" aria-hidden>
      {tgt != null && (
        <div
          className="absolute inset-y-0 bg-gray-200 dark:bg-gray-700"
          style={{ left: `${lo}%`, width: `${Math.max(hi - lo, 0)}%` }}
        />
      )}
      <div
        className="absolute inset-y-0 left-0 rounded-full opacity-90"
        style={{ width: `${cur}%`, background: ARCA_LETTER_COLOR[l.key] }}
      />
      {tgt != null && (
        <div
          className="absolute inset-y-[-2px] w-0.5 bg-gray-900 dark:bg-white"
          style={{ left: `calc(${tgt}% - 1px)` }}
        />
      )}
    </div>
  )
}

export default function ArcaCard({
  workspaceId,
  summary,
}: {
  workspaceId: string
  summary: ArcaSummaryOut
}) {
  const [open, setOpen] = useState<Record<string, boolean>>({})
  const [amount, setAmount] = useState('')
  const [plan, setPlan] = useState<ArcaPlanOut | null>(null)
  const [planError, setPlanError] = useState('')
  const [planning, setPlanning] = useState(false)

  async function simulate() {
    const v = parseAmount(amount)
    if (v == null || v <= 0) {
      setPlanError('Informe um valor maior que zero.')
      return
    }
    setPlanning(true)
    setPlanError('')
    try {
      setPlan(await api.arcaContributionPlan(workspaceId, String(v)))
    } catch (e) {
      setPlan(null)
      setPlanError(e instanceof Error ? e.message : 'Erro ao simular.')
    } finally {
      setPlanning(false)
    }
  }

  const total = n(summary.total_brl)
  return (
    <Card>
      <div className="flex flex-wrap items-start justify-between gap-3 mb-4">
        <div>
          <h2 className="text-sm font-semibold text-gray-900 dark:text-white">Carteira ARCA</h2>
          <p className="text-[11px] text-gray-500 dark:text-gray-400 mt-0.5 max-w-xl">
            Ações · Real Estate · Caixa · Ativos internacionais. Barra = atual,
            traço = meta, faixa cinza = banda de tolerância. Base:{' '}
            <span className="money">{fmtBRL(total)}</span>
            {summary.as_of && <> (fechamento de {summary.as_of.split('-').reverse().join('/')})</>}.
          </p>
        </div>
        <div className="flex gap-4 text-right">
          <div>
            <div className="text-[10px] uppercase text-gray-500 dark:text-gray-400">Ataque</div>
            <div className="text-sm font-semibold tnum" data-testid="arca-attack">{fmtPct(summary.attack_pct)}</div>
          </div>
          <div>
            <div className="text-[10px] uppercase text-gray-500 dark:text-gray-400">Defesa</div>
            <div className="text-sm font-semibold tnum">{fmtPct(summary.defense_pct)}</div>
          </div>
          <div>
            <div className="text-[10px] uppercase text-gray-500 dark:text-gray-400">Renda 12m</div>
            <div className="text-sm font-semibold tnum money">{fmtBRL(n(summary.income_12m_total_brl))}</div>
          </div>
        </div>
      </div>

      {!summary.targets_configured && (
        <div className="mb-3 rounded-md border border-amber-200 dark:border-amber-900 bg-amber-50 dark:bg-amber-900/20 p-3 text-[12px] text-amber-800 dark:text-amber-300">
          Sem metas ARCA. Defina em{' '}
          <a className="underline" href="/admin/target-allocation?tab=ARCA">Alocação alvo → ARCA</a>{' '}
          (tem um ponto de partida do método para editar).
        </div>
      )}
      {summary.unmapped_count > 0 && (
        <div
          data-testid="arca-unmapped"
          className="mb-3 flex items-center gap-2 rounded-md border border-gray-200 dark:border-gray-800 p-3 text-[12px] text-gray-700 dark:text-gray-300"
        >
          <AlertTriangle className="w-4 h-4 text-amber-500 shrink-0" />
          <span>
            {summary.unmapped_count} ativo(s) sem classificação ARCA (
            <span className="money">{fmtBRL(n(summary.unmapped_brl))}</span>) ficaram fora da conta.{' '}
            <a className="underline" href="/decision-support/arca-classification?pending=1">Classificar</a>
          </span>
        </div>
      )}

      <div className="overflow-x-auto">
        <table className="w-full text-[12px] min-w-[640px]">
          <thead>
            <tr className="border-b border-gray-200 dark:border-gray-800 text-[10px] uppercase tracking-wider text-gray-500 dark:text-gray-400">
              <th className="text-left py-1.5 font-medium">Letra</th>
              <th className="text-left py-1.5 font-medium w-1/4">Atual × meta</th>
              <th className="text-right py-1.5 font-medium">Atual</th>
              <th className="text-right py-1.5 font-medium">Meta</th>
              <th className="text-right py-1.5 font-medium">Falta</th>
              <th className="text-right py-1.5 font-medium">Renda 12m</th>
              <th className="text-right py-1.5 font-medium">Yield</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
            {summary.letters.map((l) => {
              const isOpen = !!open[l.key]
              const assets = summary.assets.filter((a) => a.category === l.key)
              return [
                <tr
                  key={l.key}
                  data-testid={`arca-letter-${l.key}`}
                  className="cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-800/40"
                  onClick={() => setOpen((o) => ({ ...o, [l.key]: !o[l.key] }))}
                >
                  <td className="py-2">
                    <div className="flex items-center gap-1.5">
                      {isOpen ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
                      <span
                        className="inline-flex w-5 h-5 items-center justify-center rounded text-[10px] font-bold text-white"
                        style={{ background: ARCA_LETTER_COLOR[l.key] }}
                      >
                        {ARCA_LETTER_SHORT[l.key]}
                      </span>
                      <span className="font-medium text-gray-900 dark:text-white">{ARCA_LETTER_LABEL[l.key]}</span>
                      <span className={`ml-1 px-1.5 py-0.5 rounded text-[10px] ${STATUS_CLASS[l.status]}`}>
                        {STATUS_LABEL[l.status]}
                      </span>
                    </div>
                  </td>
                  <td className="py-2 pr-3"><LetterBar l={l} /></td>
                  <td className="py-2 text-right tnum">{fmtPct(l.current_pct)}</td>
                  <td className="py-2 text-right tnum text-gray-500">
                    {l.target_pct != null ? fmtPct(n(l.target_pct)) : '—'}
                  </td>
                  <td className="py-2 text-right tnum money">
                    {l.gap_brl != null ? fmtBRL(n(l.gap_brl), { sign: true }) : '—'}
                  </td>
                  <td className="py-2 text-right tnum money">{fmtBRL(n(l.income_12m_brl))}</td>
                  <td className="py-2 text-right tnum">{fmtPct(l.yield_12m)}</td>
                </tr>,
                isOpen && (
                  <tr key={`${l.key}-detail`} className="bg-gray-50/60 dark:bg-gray-800/20">
                    <td colSpan={7} className="px-6 py-3">
                      {l.subcategories.length === 0 && n(l.unclassified_sub_value_brl) === 0 && (
                        <div className="text-[11px] text-gray-500 italic">Nada nesta letra ainda.</div>
                      )}
                      {l.subcategories.length > 0 && (
                        <table className="w-full text-[11px] mb-2">
                          <thead>
                            <tr className="text-[10px] uppercase text-gray-500 dark:text-gray-400">
                              <th className="text-left py-1 font-medium">Subcategoria</th>
                              <th className="text-right py-1 font-medium">% da letra</th>
                              <th className="text-right py-1 font-medium">Meta na letra</th>
                              <th className="text-right py-1 font-medium">% do total</th>
                              <th className="text-right py-1 font-medium">Falta</th>
                              <th className="text-right py-1 font-medium">Yield 12m</th>
                            </tr>
                          </thead>
                          <tbody>
                            {l.subcategories.map((s) => (
                              <tr key={s.key} data-testid={`arca-sub-${s.key}`}>
                                <td className="py-1">
                                  {ARCA_SUB_LABEL[s.key] ?? s.key}{' '}
                                  <span className="text-[10px] text-gray-400">
                                    {s.role === 'ATTACK' ? 'ataque' : 'defesa'}
                                  </span>
                                </td>
                                <td className="py-1 text-right tnum">{fmtPct(s.pct_of_letter)}</td>
                                <td className="py-1 text-right tnum text-gray-500">
                                  {s.target_pct_of_letter != null ? fmtPct(n(s.target_pct_of_letter)) : '—'}
                                </td>
                                <td className="py-1 text-right tnum">{fmtPct(s.pct_of_total)}</td>
                                <td className="py-1 text-right tnum money">
                                  {s.gap_brl != null ? fmtBRL(n(s.gap_brl), { sign: true }) : '—'}
                                </td>
                                <td className="py-1 text-right tnum">{fmtPct(s.yield_12m)}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      )}
                      {n(l.unclassified_sub_value_brl) > 0 && (
                        <div className="text-[11px] text-amber-700 dark:text-amber-400 mb-2">
                          <span className="money">{fmtBRL(n(l.unclassified_sub_value_brl))}</span> sem subcategoria —{' '}
                          <a className="underline" href="/decision-support/arca-classification">classificar</a>
                        </div>
                      )}
                      {n(l.income_forward_brl) > 0 && (
                        <div className="text-[11px] text-gray-500 mb-2">
                          Renda estimada pelo DY dos fundamentos:{' '}
                          <span className="money">{fmtBRL(n(l.income_forward_brl))}</span>/ano
                        </div>
                      )}
                      {assets.length > 0 && (
                        <div className="flex flex-wrap gap-1.5">
                          {assets.map((a) => (
                            <a
                              key={a.asset_id}
                              href={`/assets/${a.asset_id}`}
                              className="px-1.5 py-0.5 rounded border border-gray-200 dark:border-gray-700 text-[10px] hover:border-indigo-400"
                              title={a.subcategory ? ARCA_SUB_LABEL[a.subcategory] : 'sem subcategoria'}
                            >
                              {a.ticker || a.name}
                            </a>
                          ))}
                        </div>
                      )}
                    </td>
                  </tr>
                ),
              ]
            })}
          </tbody>
        </table>
      </div>

      {/* ── Simulador de aporte ── */}
      <div className="mt-5 border-t border-gray-100 dark:border-gray-800 pt-4">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-700 dark:text-gray-300 mb-1">
          Simular aporte
        </h3>
        <p className="text-[11px] text-gray-500 dark:text-gray-400 mb-2">
          Rebalanceia pelo aporte: o dinheiro vai primeiro para a letra mais atrasada.
          Venda só aparece quando uma letra passa do teto da banda (lembre do IR).
        </p>
        <form
          className="flex gap-2 items-center"
          onSubmit={(e) => { e.preventDefault(); simulate() }}
        >
          <input
            data-testid="arca-amount"
            inputMode="decimal"
            placeholder="R$ 10.000"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            className="h-8 w-40 rounded-md border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-900 px-2 text-[13px] tnum"
          />
          <button
            type="submit"
            data-testid="arca-simulate"
            disabled={planning || !summary.targets_configured}
            className="h-8 px-3 text-[12px] font-medium rounded-md bg-indigo-500 hover:bg-indigo-400 text-white disabled:opacity-50"
          >
            {planning ? 'Calculando…' : 'Simular'}
          </button>
        </form>
        {planError && <div className="mt-2 text-[12px] text-red-600">{planError}</div>}
        {plan && (
          <table className="mt-3 w-full text-[12px]" data-testid="arca-plan">
            <thead>
              <tr className="text-[10px] uppercase text-gray-500 dark:text-gray-400 border-b border-gray-200 dark:border-gray-800">
                <th className="text-left py-1 font-medium">Letra</th>
                <th className="text-right py-1 font-medium">Aportar</th>
                <th className="text-left py-1 pl-4 font-medium">Onde</th>
                <th className="text-right py-1 font-medium">Depois</th>
                <th className="text-right py-1 font-medium">Meta</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
              {plan.letters.map((l) => (
                <tr key={l.key}>
                  <td className="py-1.5">{ARCA_LETTER_LABEL[l.key]}</td>
                  <td className="py-1.5 text-right tnum font-medium money">{fmtBRL(n(l.amount_brl))}</td>
                  <td className="py-1.5 pl-4 text-[11px] text-gray-600 dark:text-gray-400">
                    {l.subcategories.map((s) => `${ARCA_SUB_LABEL[s.key] ?? s.key} ${fmtBRL(n(s.amount_brl))}`).join(' · ')}
                    {n(l.sell_suggestion_brl) > 0 && (
                      <span className="text-red-600 dark:text-red-400">
                        {' '}Acima do teto: vender ~{fmtBRL(n(l.sell_suggestion_brl))}
                      </span>
                    )}
                  </td>
                  <td className="py-1.5 text-right tnum">{fmtPct(l.after_pct)}</td>
                  <td className="py-1.5 text-right tnum text-gray-500">{fmtPct(n(l.target_pct))}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </Card>
  )
}
