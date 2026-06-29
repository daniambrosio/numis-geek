import { useEffect, useState } from 'react'
import { RefreshCcw } from 'lucide-react'

import { api, type ValuationOut } from '../lib/api'
import { Card } from './ui'
import VerdictBadge from './VerdictBadge'

interface Props {
  assetId: string
  canRefresh?: boolean
}

function fmtMetric(value: string | null, unit: string): string {
  if (value === null) return '—'
  const n = Number(value)
  if (Number.isNaN(n)) return '—'
  if (unit === 'pct') return `${(n * 100).toFixed(2)}%`
  if (unit === 'currency') {
    if (n >= 1e9) return `${(n / 1e9).toFixed(2)}B`
    if (n >= 1e6) return `${(n / 1e6).toFixed(2)}M`
    return n.toLocaleString('pt-BR', { maximumFractionDigits: 2 })
  }
  if (unit === 'price') return n.toLocaleString('pt-BR', { maximumFractionDigits: 2 })
  // ratio
  return n.toFixed(2)
}

function interpretTone(interpretation: string): string {
  if (interpretation === 'cheap') return 'text-emerald-600 dark:text-emerald-400'
  if (interpretation === 'expensive') return 'text-red-600 dark:text-red-400'
  return 'text-gray-700 dark:text-gray-300'
}

export default function ValuationCard({ assetId, canRefresh = false }: Props) {
  const [val, setVal] = useState<ValuationOut | null>(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    setLoading(true); setError('')
    api.getValuation(assetId)
      .then(setVal)
      .catch((e) => setError(e instanceof Error ? e.message : 'Erro ao carregar valuation.'))
      .finally(() => setLoading(false))
  }, [assetId])

  async function handleRefresh() {
    setRefreshing(true); setError('')
    try {
      await api.refreshFundamentals(assetId)
      const fresh = await api.getValuation(assetId)
      setVal(fresh)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Falha ao atualizar fundamentos.')
    } finally {
      setRefreshing(false)
    }
  }

  return (
    <Card>
      <div className="flex items-start justify-between mb-3">
        <div>
          <h3 className="text-sm font-semibold text-gray-900 dark:text-white">Valuation</h3>
          <p className="text-[11px] text-gray-500 dark:text-gray-400 mt-0.5">
            Verdict + métricas fundamentalistas. Calibração das regras em <code>spec 61b</code>.
          </p>
        </div>
        {canRefresh && (
          <button
            data-testid="valuation-refresh"
            onClick={handleRefresh}
            disabled={refreshing || loading}
            title="Atualizar fundamentos do provedor"
            className="inline-flex items-center gap-1 h-7 px-2 text-[11px] rounded-md bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700 disabled:opacity-50"
          >
            <RefreshCcw className={`w-3 h-3 ${refreshing ? 'animate-spin' : ''}`} />
            {refreshing ? 'Atualizando…' : 'Atualizar'}
          </button>
        )}
      </div>

      {loading && (
        <div className="text-[12px] text-gray-500">Carregando…</div>
      )}
      {error && (
        <div
          data-testid="valuation-error"
          className="rounded-md border border-red-200 dark:border-red-900 bg-red-50 dark:bg-red-900/20 p-2 text-[12px] text-red-700 dark:text-red-300 mb-3"
        >
          {error}
        </div>
      )}

      {val && (
        <div className="space-y-3">
          <div className="flex items-center gap-2 flex-wrap">
            <VerdictBadge verdict={val.verdict} title={val.verdict_reason} />
            {val.is_stale && val.fundamentals_as_of && (
              <span
                title={`Fundamentos de ${val.fundamentals_as_of}`}
                className="inline-flex items-center px-1.5 py-0.5 rounded-full text-[10px] bg-amber-500/15 text-amber-700 dark:text-amber-300"
              >
                Fundamentos antigos
              </span>
            )}
            {val.fundamentals_source && (
              <span className="text-[10px] text-gray-500 dark:text-gray-500">
                via {val.fundamentals_source} · {val.fundamentals_as_of}
              </span>
            )}
          </div>

          <p className="text-[12px] text-gray-600 dark:text-gray-400 leading-relaxed">
            {val.verdict_reason}
          </p>

          {val.disqualifying.length > 0 && (
            <div className="rounded-md bg-amber-500/10 border border-amber-500/30 p-2 text-[11px]">
              <div className="font-medium text-amber-800 dark:text-amber-300 mb-1">
                Disqualifying gates ativos
              </div>
              <ul className="list-disc list-inside text-amber-700 dark:text-amber-400 space-y-0.5">
                {val.disqualifying.map((g, i) => <li key={i}>{g}</li>)}
              </ul>
            </div>
          )}

          {val.metrics.length > 0 && (
            <table className="w-full text-[12px]">
              <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
                {val.metrics.map((m) => (
                  <tr key={m.name}>
                    <td className="py-1.5 text-gray-600 dark:text-gray-400">{m.name}</td>
                    <td className={`py-1.5 text-right tnum font-medium ${interpretTone(m.interpretation)}`}>
                      {fmtMetric(m.value, m.unit)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </Card>
  )
}
