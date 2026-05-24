import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ChevronRight, Plus } from 'lucide-react'
import { api, type OpenOptionOut } from '../lib/api'
import { KLASS } from '../lib/tokens'

interface Props {
  underlyingId: string
  underlyingTicker: string
  onAction?: () => void   // callback after exercise/expire/close to refresh parent
  onAddOption?: () => void // opens the OptionModal in the parent
}

function fmtBRL(n: number, opts: { sign?: boolean } = {}) {
  const v = opts.sign ? Math.abs(n) : n
  const sign = opts.sign && n > 0 ? '+ ' : opts.sign && n < 0 ? '− ' : ''
  return sign + v.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })
}

function fmtNum(n: number) {
  return n.toLocaleString('pt-BR', { maximumFractionDigits: 0 })
}

export default function OpenOptionsCard({ underlyingId, underlyingTicker, onAction, onAddOption }: Props) {
  const [rows, setRows] = useState<OpenOptionOut[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState<string | null>(null)

  function refresh() {
    setLoading(true)
    api.listOpenOptionsForUnderlying(underlyingId)
      .then(setRows)
      .catch(e => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false))
  }

  useEffect(refresh, [underlyingId])

  async function handleExpire(id: string) {
    if (!confirm('Marcar como vencida (virou pó)?')) return
    setBusy(id)
    try {
      await api.expireOption(id)
      refresh()
      onAction?.()
    } catch (e) {
      alert(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(null)
    }
  }

  async function handleExercise(id: string) {
    const d = prompt('Data do exercício (YYYY-MM-DD):', new Date().toISOString().slice(0, 10))
    if (!d) return
    setBusy(id)
    try {
      await api.exerciseOption(id, d)
      refresh()
      onAction?.()
    } catch (e) {
      alert(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(null)
    }
  }

  if (loading) {
    return (
      <div className="rounded-xl bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 p-3">
        <div className="text-[11px] text-gray-400">Carregando opções...</div>
      </div>
    )
  }
  // Empty state: only render if the parent provides an add-option handler;
  // otherwise hide the card (matches prototype behavior).
  if (rows.length === 0) {
    if (!onAddOption) return null
    return (
      <div className="rounded-xl bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 p-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="w-1.5 h-3 rounded-full" style={{ background: KLASS.OPTION.color }} />
            <span className="text-[12px] font-semibold text-gray-900 dark:text-white">
              Opções abertas sobre {underlyingTicker} · 0
            </span>
          </div>
          <button
            onClick={onAddOption}
            className="h-7 px-2.5 inline-flex items-center gap-1 rounded-md text-[11px] font-medium bg-indigo-500 hover:bg-indigo-400 text-white transition-colors"
          >
            <Plus className="w-3 h-3" /> Nova opção
          </button>
        </div>
        <div className="mt-3 text-[11px] text-gray-500 dark:text-gray-400">
          Sem opções abertas. Use <strong>+ Nova opção</strong> pra lançar uma covered call ou cash-secured put sobre {underlyingTicker}.
        </div>
      </div>
    )
  }
  if (error) {
    return (
      <div className="rounded-xl bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-900 p-3 text-[12px] text-red-600 dark:text-red-400">{error}</div>
    )
  }

  const totalPremium = rows.reduce((s, r) => s + r.premium_received, 0)

  return (
    <div className="rounded-xl bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 p-3 space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="w-1.5 h-3 rounded-full" style={{ background: KLASS.OPTION.color }} />
          <span className="text-[12px] font-semibold text-gray-900 dark:text-white">
            Opções abertas sobre {underlyingTicker} · {rows.length}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[11px] text-gray-500">
            Prêmio total recebido <span className={`tnum font-medium ${totalPremium >= 0 ? 'text-emerald-500 dark:text-emerald-400' : 'text-red-500 dark:text-red-400'}`}>{fmtBRL(totalPremium, { sign: true })}</span>
          </span>
          {onAddOption && (
            <button
              onClick={onAddOption}
              className="h-7 px-2.5 inline-flex items-center gap-1 rounded-md text-[11px] font-medium bg-indigo-500 hover:bg-indigo-400 text-white transition-colors"
            >
              <Plus className="w-3 h-3" /> Nova opção
            </button>
          )}
        </div>
      </div>

      <div className="space-y-2">
        {rows.map(r => {
          const verdictLabel = r.verdict === 'likely_exercise' ? 'Provável exercício'
            : r.verdict === 'likely_worthless' ? 'Provável virar pó'
            : '—'
          const verdictColor = r.verdict === 'likely_exercise' ? 'text-amber-500 dark:text-amber-400'
            : r.verdict === 'likely_worthless' ? 'text-emerald-500 dark:text-emerald-400'
            : 'text-gray-400'
          return (
            <Link
              key={r.option_id}
              to={`/assets/${r.option_id}`}
              className="block p-3 -mx-1 rounded-lg border border-gray-200 dark:border-gray-800 hover:bg-gray-50 dark:hover:bg-gray-800/30 hover:border-indigo-500/40 transition-colors group"
            >
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2 min-w-0 flex-wrap">
                  <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium uppercase tracking-wider ${
                    r.option_type === 'PUT' ? 'bg-blue-500/15 text-blue-500 dark:text-blue-400'
                    : 'bg-violet-500/15 text-violet-500 dark:text-violet-300'
                  }`}>
                    {r.option_type} · {r.is_short ? 'vendida' : 'comprada'}
                  </span>
                  <span className="font-mono text-[12px] font-medium text-gray-900 dark:text-white group-hover:text-indigo-500 dark:group-hover:text-indigo-300 transition-colors">{r.ticker}</span>
                  <span className="text-[11px] text-gray-500">strike <span className="tnum font-medium">{fmtBRL(r.strike)}</span></span>
                </div>
                <div className="text-right shrink-0 flex items-center gap-2">
                  <div>
                    <div className={`text-[11px] font-medium ${verdictColor}`}>{verdictLabel}</div>
                    <div className="text-[10px] text-gray-500 tnum">
                      {r.days_to_expiration === 0 ? 'venceu' : `vence em ${r.days_to_expiration}d`}
                    </div>
                  </div>
                  <ChevronRight className="w-4 h-4 text-gray-400 dark:text-gray-600 group-hover:text-indigo-500 dark:group-hover:text-indigo-300 transition-colors" />
                </div>
              </div>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mb-2 text-[11px]">
                <div>
                  <div className="text-[9px] uppercase tracking-wider text-gray-500">Prêmio</div>
                  <div className="tnum font-medium text-emerald-500 dark:text-emerald-400">{fmtBRL(r.premium_received, { sign: true })}</div>
                  <div className="text-[10px] text-gray-400">{fmtBRL(r.premium_per_share)}/ação × {fmtNum(r.qty)}</div>
                </div>
                {r.mark_to_market != null ? (
                  <div>
                    <div className="text-[9px] uppercase tracking-wider text-gray-500">Mark-to-market</div>
                    <div className="tnum font-medium">{fmtBRL(r.mark_to_market)}</div>
                    {r.current_price != null && (
                      <div className="text-[10px] text-gray-400">{fmtBRL(r.current_price)} atual</div>
                    )}
                  </div>
                ) : <div></div>}
                {r.close_now_pnl != null ? (
                  <div>
                    <div className="text-[9px] uppercase tracking-wider text-gray-500">Se fechasse</div>
                    <div className={`tnum font-medium ${r.close_now_pnl >= 0 ? 'text-emerald-500 dark:text-emerald-400' : 'text-red-500 dark:text-red-400'}`}>
                      {fmtBRL(r.close_now_pnl, { sign: true })}
                    </div>
                  </div>
                ) : <div></div>}
                <div>
                  <div className="text-[9px] uppercase tracking-wider text-gray-500">
                    {r.option_type === 'PUT' ? 'Preço efetivo (BUY)' : 'Preço efetivo (SELL)'}
                  </div>
                  {r.effective_price != null && (
                    <>
                      <div className="tnum font-medium">{fmtBRL(r.effective_price)}</div>
                      <div className="text-[10px] text-gray-400">se exercida</div>
                    </>
                  )}
                </div>
              </div>
              <div className="flex items-center justify-end gap-1">
                <button
                  onClick={(e) => { e.preventDefault(); e.stopPropagation(); handleExercise(r.option_id) }}
                  disabled={busy === r.option_id}
                  className="h-6 px-2 inline-flex items-center rounded-md text-[10px] border border-amber-200 dark:border-amber-900/40 text-amber-600 dark:text-amber-400 hover:bg-amber-50 dark:hover:bg-amber-900/20 disabled:opacity-50"
                  title="Marcar como exercida — gera BUY/SELL no underlying com preço efetivo"
                >
                  Exercer
                </button>
                <button
                  onClick={(e) => { e.preventDefault(); e.stopPropagation(); handleExpire(r.option_id) }}
                  disabled={busy === r.option_id}
                  className="h-6 px-2 inline-flex items-center rounded-md text-[10px] border border-gray-200 dark:border-gray-700 text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-800 disabled:opacity-50"
                  title="Marcar como vencida sem ser exercida"
                >
                  Virou pó
                </button>
              </div>
            </Link>
          )
        })}
      </div>

      <div className="text-[10px] text-gray-500 dark:text-gray-400 pt-2 border-t border-gray-200 dark:border-gray-800">
        Prêmios entram em /proventos como <span className="font-medium" style={{ color: KLASS.OPTION.color }}>Dividendo sintético</span> — não inflam o DY/YoC de {underlyingTicker}.
      </div>
    </div>
  )
}
