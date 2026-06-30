import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AlertTriangle, Compass, Sparkles } from 'lucide-react'

import AppLayout from '../components/AppLayout'
import EfficientFrontierChart from '../components/EfficientFrontierChart'
import GapVsTargetChart from '../components/GapVsTargetChart'
import SuggestedTradesTable from '../components/SuggestedTradesTable'
import VerdictBadge from '../components/VerdictBadge'
import { Card, ClassBadge, PageHeader } from '../components/ui'
import {
  api,
  type AssetOut,
  type OptimizeOut,
  type PortfolioOut,
  type TargetAllocationOut,
  type UserOut,
  type ValuationOut,
} from '../lib/api'
import { type CollapsedClassCode } from '../lib/tokens'

interface GapSlice {
  key: string
  current_pct: number
  target_pct: number
}

function pct(n: number): string {
  return `${(n * 100).toFixed(1)}%`
}

function buildGapSlices(
  portfolio: PortfolioOut | null,
  targets: { entries: { key: string; target_pct: string }[] },
  dim: 'CLASS' | 'COUNTRY',
): GapSlice[] {
  if (!portfolio) return []
  const total = portfolio.total_value_brl || 1
  const targetMap = new Map(
    targets.entries.map((e) => [e.key, Number(e.target_pct)]),
  )
  const byKey = new Map<string, number>()
  if (dim === 'CLASS') {
    for (const c of portfolio.by_class) {
      byKey.set(c.asset_class, (byKey.get(c.asset_class) || 0) + c.value_brl)
    }
  } else {
    for (const c of portfolio.by_country) {
      byKey.set(c.country, (byKey.get(c.country) || 0) + c.value_brl)
    }
  }
  const allKeys = new Set<string>([...byKey.keys(), ...targetMap.keys()])
  return Array.from(allKeys).map((k) => ({
    key: k,
    current_pct: (byKey.get(k) || 0) / total,
    target_pct: targetMap.get(k) || 0,
  })).sort((a, b) => b.target_pct - a.target_pct || b.current_pct - a.current_pct)
}

interface ValuationRow {
  asset: AssetOut
  result: ValuationOut | null
  error: string | null
}

export default function DecisionSupport() {
  const navigate = useNavigate()
  const [me, setMe] = useState<UserOut | null>(null)
  const [portfolio, setPortfolio] = useState<PortfolioOut | null>(null)
  const [targets, setTargets] = useState<TargetAllocationOut | null>(null)
  const [assets, setAssets] = useState<AssetOut[]>([])
  const [valuations, setValuations] = useState<ValuationRow[]>([])
  const [opt, setOpt] = useState<OptimizeOut | null>(null)
  const [optimizing, setOptimizing] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [optError, setOptError] = useState('')

  useEffect(() => {
    api.me().then(setMe).catch(() => navigate('/login'))
  }, [navigate])

  useEffect(() => {
    if (!me || !me.workspace_id) return
    setLoading(true); setError('')
    Promise.all([
      api.getPortfolio().catch((e) => { console.warn('portfolio', e); return null }),
      api.getTargetAllocation(me.workspace_id).catch((e) => { console.warn('targets', e); return null }),
      api.listAssets({}).catch((e) => { console.warn('assets', e); return [] as AssetOut[] }),
    ]).then(([p, t, a]) => {
      setPortfolio(p)
      setTargets(t)
      setAssets(a)
    }).catch((e) => {
      setError(e instanceof Error ? e.message : 'Erro ao carregar.')
    }).finally(() => setLoading(false))
  }, [me])

  // Fetch valuation for each owned asset (in parallel; bounded by browser).
  useEffect(() => {
    if (assets.length === 0) return
    const subset = assets.filter((a) => a.is_active)
    const out: ValuationRow[] = subset.map((a) => ({ asset: a, result: null, error: null }))
    setValuations(out)
    subset.forEach((a, i) => {
      api.getValuation(a.id)
        .then((res) => {
          setValuations((prev) => {
            const copy = [...prev]
            copy[i] = { asset: a, result: res, error: null }
            return copy
          })
        })
        .catch((e) => {
          setValuations((prev) => {
            const copy = [...prev]
            copy[i] = { asset: a, result: null, error: e instanceof Error ? e.message : 'erro' }
            return copy
          })
        })
    })
  }, [assets])

  const classSlices = useMemo(
    () => buildGapSlices(portfolio, targets?.CLASS ?? { entries: [] }, 'CLASS'),
    [portfolio, targets],
  )
  const countrySlices = useMemo(
    () => buildGapSlices(portfolio, targets?.COUNTRY ?? { entries: [] }, 'COUNTRY'),
    [portfolio, targets],
  )

  async function runOptimize() {
    setOptimizing(true); setOptError('')
    try {
      const result = await api.optimizePortfolio({
        asset_cap: '0.15',
        country_caps: { BR: '0.70' },
      })
      setOpt(result)
    } catch (e) {
      setOptError(e instanceof Error ? e.message : 'Erro ao otimizar')
      setOpt(null)
    } finally {
      setOptimizing(false)
    }
  }

  if (!me) return null

  // Empty-state guards
  const hasTargets =
    (targets?.CLASS.entries.length ?? 0) > 0 ||
    (targets?.COUNTRY.entries.length ?? 0) > 0
  const hasPortfolio = portfolio && portfolio.source !== 'empty'
  const sortedValuations = [...valuations].sort((a, b) => {
    const order = { BUY: 0, SELL: 1, HOLD: 2, NA: 3 }
    const av = a.result?.verdict || 'NA'
    const bv = b.result?.verdict || 'NA'
    return (order[av] - order[bv]) ||
      (a.asset.ticker || a.asset.name).localeCompare(b.asset.ticker || b.asset.name)
  })

  return (
    <AppLayout user={me}>
      <div className="space-y-6">
        <PageHeader
          title="Suporte à Decisão"
          countLabel="ativos"
          count={portfolio?.top_holdings.length ?? null}
        />
        <p className="text-[13px] text-gray-500 dark:text-gray-400 -mt-2 max-w-3xl">
          Decisões de aporte/rebalance baseadas em (a) gap vs alocação alvo,
          (b) otimização média-variância (Markowitz) com hard constraints e
          (c) valuation fundamentalista por classe. Configure metas em{' '}
          <a className="underline" href="/admin/target-allocation">Alocação alvo</a>.
        </p>

        {loading && (
          <div className="text-[12px] text-gray-500">Carregando…</div>
        )}
        {error && (
          <div className="rounded-lg border border-red-200 dark:border-red-900 bg-red-50 dark:bg-red-900/20 p-4 text-[13px] text-red-700 dark:text-red-300">
            {error}
          </div>
        )}

        {!hasPortfolio && !loading && (
          <Card>
            <div className="text-center py-8">
              <Compass className="w-7 h-7 mx-auto text-indigo-500 dark:text-indigo-400 mb-3" />
              <p className="text-sm font-medium">Sem snapshots de portfólio.</p>
              <p className="text-[12px] text-gray-500 dark:text-gray-400 mt-2">
                Decision Support depende de pelo menos 12 fechamentos mensais
                pra rodar Markowitz. Crie snapshots em /snapshots primeiro.
              </p>
            </div>
          </Card>
        )}

        {!hasTargets && hasPortfolio && (
          <Card>
            <div className="text-center py-6">
              <AlertTriangle className="w-6 h-6 mx-auto text-amber-500 mb-2" />
              <p className="text-sm font-medium">Sem alocação alvo cadastrada.</p>
              <p className="text-[12px] text-gray-500 dark:text-gray-400 mt-1">
                Configure metas por classe e por país em{' '}
                <a className="underline" href="/admin/target-allocation">/admin/target-allocation</a>{' '}
                pra ativar gap-vs-target e Markowitz.
              </p>
            </div>
          </Card>
        )}

        {/* ── (a) Gap vs Target ─────────────────────────────────────── */}
        {hasPortfolio && hasTargets && (
          <Card>
            <h2 className="text-sm font-semibold text-gray-900 dark:text-white mb-3">
              Gap vs Alocação Alvo
            </h2>
            {(targets?.CLASS.entries.length ?? 0) > 0 && (
              <GapVsTargetChart
                dimension="CLASS" title="Por classe" slices={classSlices}
              />
            )}
            {(targets?.COUNTRY.entries.length ?? 0) > 0 && (
              <div className="mt-4">
                <GapVsTargetChart
                  dimension="COUNTRY" title="Por país" slices={countrySlices}
                />
              </div>
            )}
          </Card>
        )}

        {/* ── (b) Markowitz ─────────────────────────────────────────── */}
        {hasPortfolio && hasTargets && (
          <Card>
            <div className="flex items-start justify-between mb-3">
              <div>
                <h2 className="text-sm font-semibold text-gray-900 dark:text-white">
                  Otimização Markowitz
                </h2>
                <p className="text-[11px] text-gray-500 dark:text-gray-400 mt-0.5">
                  Min-variance respeitando metas por classe (equality), cap 15%
                  por ativo, cap 70% Brasil, no-short. Retornos mensais em BRL.
                </p>
              </div>
              <button
                data-testid="optimize-btn"
                onClick={runOptimize}
                disabled={optimizing}
                className="inline-flex items-center gap-1.5 h-8 px-3 text-[12px] font-medium rounded-md bg-indigo-500 hover:bg-indigo-400 text-white disabled:opacity-50"
              >
                <Sparkles className="w-3.5 h-3.5" />
                {optimizing ? 'Otimizando…' : (opt ? 'Recomputar' : 'Otimizar')}
              </button>
            </div>

            {optError && (
              <div
                data-testid="opt-error"
                className="rounded-md border border-red-200 dark:border-red-900 bg-red-50 dark:bg-red-900/20 p-3 text-[12px] text-red-700 dark:text-red-300 mb-3"
              >
                {optError}
              </div>
            )}

            {opt && (
              <div className="space-y-4">
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                  <div>
                    <div className="text-[10px] uppercase text-gray-500 dark:text-gray-400">Ativos elegíveis</div>
                    <div className="text-sm font-semibold tnum">{opt.n_assets}</div>
                  </div>
                  <div>
                    <div className="text-[10px] uppercase text-gray-500 dark:text-gray-400">Retorno esperado</div>
                    <div className="text-sm font-semibold tnum text-emerald-600 dark:text-emerald-400">{pct(opt.expected_return)}</div>
                  </div>
                  <div>
                    <div className="text-[10px] uppercase text-gray-500 dark:text-gray-400">Volatilidade</div>
                    <div className="text-sm font-semibold tnum">{pct(opt.volatility)}</div>
                  </div>
                  <div>
                    <div className="text-[10px] uppercase text-gray-500 dark:text-gray-400">Excluídos</div>
                    <div className="text-sm font-semibold tnum">{opt.n_excluded}</div>
                  </div>
                </div>

                <EfficientFrontierChart
                  frontier={opt.frontier}
                  optimalPoint={{ ret: opt.expected_return, vol: opt.volatility }}
                />

                {opt.warnings.length > 0 && (
                  <ul className="text-[11px] text-amber-700 dark:text-amber-400 space-y-0.5">
                    {opt.warnings.map((w, i) => <li key={i}>⚠ {w}</li>)}
                  </ul>
                )}
                {opt.binding_constraints.length > 0 && (
                  <div className="text-[11px] text-gray-500 dark:text-gray-400">
                    Restrições ativas: {opt.binding_constraints.join(', ')}
                  </div>
                )}

                <div>
                  <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-700 dark:text-gray-300 mb-2">
                    Trades sugeridos
                  </h3>
                  <SuggestedTradesTable allocations={opt.optimal} />
                </div>

                {opt.excluded.length > 0 && (
                  <details className="text-[12px]">
                    <summary className="cursor-pointer text-gray-600 dark:text-gray-400">
                      {opt.excluded.length} ativo(s) excluído(s) — clique pra ver
                    </summary>
                    <ul className="mt-2 space-y-0.5 text-[11px] text-gray-500 dark:text-gray-500">
                      {opt.excluded.map((e) => (
                        <li key={e.asset_id}>
                          {e.ticker || e.name} — {e.reason}
                        </li>
                      ))}
                    </ul>
                  </details>
                )}
              </div>
            )}
          </Card>
        )}

        {/* ── (c) Valuation por ativo ───────────────────────────────── */}
        {hasPortfolio && (
          <Card>
            <h2 className="text-sm font-semibold text-gray-900 dark:text-white mb-3">
              Valuation por ativo
            </h2>
            {sortedValuations.length === 0 ? (
              <div className="text-[12px] text-gray-500 italic py-4 text-center">
                Sem ativos pra analisar.
              </div>
            ) : (
              <table className="w-full text-[12px]">
                <thead>
                  <tr className="border-b border-gray-200 dark:border-gray-800 text-[10px] uppercase tracking-wider text-gray-500 dark:text-gray-400">
                    <th className="text-left py-1.5 font-medium">Ativo</th>
                    <th className="text-left py-1.5 font-medium">Classe</th>
                    <th className="text-left py-1.5 font-medium">Veredito</th>
                    <th className="text-left py-1.5 font-medium pr-1">Razão</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
                  {sortedValuations.map((row) => (
                    <tr
                      key={row.asset.id}
                      data-testid={`val-row-${row.asset.id}`}
                      className="hover:bg-gray-50 dark:hover:bg-gray-800/40 cursor-pointer"
                      onClick={() => navigate(`/assets/${row.asset.id}`)}
                    >
                      <td className="py-1.5 font-medium text-gray-900 dark:text-white">
                        {row.asset.ticker || row.asset.name}
                      </td>
                      <td className="py-1.5">
                        <ClassBadge klass={row.asset.asset_class as CollapsedClassCode} />
                      </td>
                      <td className="py-1.5">
                        {row.result ? (
                          <VerdictBadge verdict={row.result.verdict} size="sm" />
                        ) : row.error ? (
                          <span className="text-[10px] text-red-500">erro</span>
                        ) : (
                          <span className="text-[10px] text-gray-400">…</span>
                        )}
                      </td>
                      <td className="py-1.5 text-[11px] text-gray-600 dark:text-gray-400 truncate max-w-md">
                        {row.result?.verdict_reason || ''}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Card>
        )}
      </div>
    </AppLayout>
  )
}
