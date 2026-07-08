/* Spec 62 — Bloco de detecção de variações anômalas no fechamento.
 *
 * Fica no topo do SnapshotDetail. Lista todos os ativos com delta vs
 * snapshot CLOSED anterior, sinaliza SUSPICIOUS_PENDING (bloqueiam
 * CLOSE), e permite user confirmar deltas legítimos ou disparar
 * recheck após edições manuais.
 */
import { useEffect, useMemo, useState } from 'react'
import { AlertTriangle, CheckCircle2, ChevronDown, ChevronUp, RefreshCw } from 'lucide-react'

import {
  api,
  type MoMDeltaResponse,
  type MoMDeltaRow,
  type MoMDeltaStatus,
} from '../lib/api'
import { Card, ClassBadge } from './ui'


const MONTH_NAMES_SHORT = [
  'Jan', 'Fev', 'Mar', 'Abr', 'Mai', 'Jun',
  'Jul', 'Ago', 'Set', 'Out', 'Nov', 'Dez',
]

function ymShort(iso: string | null): string {
  if (!iso) return '—'
  const [y, m] = iso.split('-')
  return `${MONTH_NAMES_SHORT[parseInt(m, 10) - 1]}/${y.slice(2)}`
}

function fmtMoney(v: string | null, currency: string): string {
  if (v == null) return '—'
  const n = Number(v)
  if (Number.isNaN(n)) return '—'
  const c = currency === 'USD' ? 'USD' : 'BRL'
  return n.toLocaleString('pt-BR', { style: 'currency', currency: c })
}

function fmtPct(v: string | null): string {
  if (v == null) return '—'
  const n = Number(v)
  if (Number.isNaN(n)) return '—'
  const pct = n * 100
  return `${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%`
}

interface Props {
  snapshotId: string
  isReadOnly: boolean  // true quando snapshot é CLOSED (só leitura)
  onResolved?: () => void  // pai re-fetcha pendencies após resolve
}

const STATUS_LABEL: Record<MoMDeltaStatus, string> = {
  OK: 'Dentro do limite',
  NEW: 'Novo ativo',
  ZEROED: 'Zerado',
  SUPPRESSED_MOVEMENT: 'Movimento no período',
  SUPPRESSED_CA: 'Evento corporativo',
  SUSPICIOUS_PENDING: 'Pendente',
  SUSPICIOUS_RESOLVED: 'Confirmado',
}

function statusBadge(status: MoMDeltaStatus): { color: string; icon: string | null } {
  switch (status) {
    case 'SUSPICIOUS_PENDING':
      return { color: 'bg-red-100 text-red-800 border-red-200', icon: '🔴' }
    case 'SUSPICIOUS_RESOLVED':
      return { color: 'bg-emerald-100 text-emerald-800 border-emerald-200', icon: '✅' }
    case 'SUPPRESSED_MOVEMENT':
      return { color: 'bg-slate-100 text-slate-700 border-slate-200', icon: '🔄' }
    case 'SUPPRESSED_CA':
      return { color: 'bg-slate-100 text-slate-700 border-slate-200', icon: '🔀' }
    case 'NEW':
      return { color: 'bg-blue-50 text-blue-700 border-blue-200', icon: '✨' }
    case 'ZEROED':
      return { color: 'bg-slate-50 text-slate-600 border-slate-200', icon: '⊘' }
    default:
      return { color: 'bg-slate-50 text-slate-500 border-slate-200', icon: null }
  }
}


export default function MoMDeltaBlock({ snapshotId, isReadOnly, onResolved }: Props) {
  const [data, setData] = useState<MoMDeltaResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [collapsed, setCollapsed] = useState(false)
  const [showAll, setShowAll] = useState(false)  // filtro: só pendentes vs todos
  const [confirmingId, setConfirmingId] = useState<string | null>(null)
  const [rechecking, setRechecking] = useState(false)

  const fetchData = async () => {
    setLoading(true)
    try {
      const r = await api.listSnapshotMomDeltas(snapshotId)
      setData(r)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void fetchData()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [snapshotId])

  const pendingRows = useMemo(
    () => (data?.rows ?? []).filter(r => r.status === 'SUSPICIOUS_PENDING'),
    [data],
  )
  const displayRows = useMemo(
    () => (showAll ? (data?.rows ?? []) : pendingRows),
    [data, showAll, pendingRows],
  )

  const handleConfirm = async (row: MoMDeltaRow) => {
    if (!row.pendency_id) return
    if (confirmingId) return
    setConfirmingId(row.pendency_id)
    try {
      await api.confirmDeltaPendency(row.pendency_id)
      await fetchData()
      onResolved?.()
    } catch (e) {
      console.error('confirmDeltaPendency error', e)
    } finally {
      setConfirmingId(null)
    }
  }

  const handleRecheck = async () => {
    if (rechecking) return
    setRechecking(true)
    try {
      await api.recheckSnapshotDeltas(snapshotId)
      await fetchData()
      onResolved?.()
    } catch (e) {
      console.error('recheckSnapshotDeltas error', e)
    } finally {
      setRechecking(false)
    }
  }

  if (loading && data === null) {
    return (
      <Card className="mb-4">
        <div className="p-3 text-sm text-slate-500">Carregando comparação MoM…</div>
      </Card>
    )
  }
  if (data === null) return null

  const pendingCount = pendingRows.length
  const prevLabel = data.previous_period_end ? ymShort(data.previous_period_end.slice(0, 7)) : null

  // Sem snapshot anterior → nada a comparar. Não polui a UI.
  if (data.previous_snapshot_id === null) return null

  return (
    <Card className="mb-4">
      <div className="flex items-center justify-between p-3 border-b border-slate-200">
        <button
          type="button"
          onClick={() => setCollapsed(v => !v)}
          className="flex items-center gap-2 text-left"
        >
          {collapsed ? <ChevronDown className="w-4 h-4" /> : <ChevronUp className="w-4 h-4" />}
          <div>
            <div className="text-sm font-semibold text-slate-800 flex items-center gap-2">
              Variações anômalas vs {prevLabel ?? 'mês anterior'}
              {pendingCount > 0 && (
                <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-red-100 text-red-700 text-xs font-medium">
                  <AlertTriangle className="w-3 h-3" />
                  {pendingCount}
                </span>
              )}
              {pendingCount === 0 && (
                <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-emerald-100 text-emerald-700 text-xs font-medium">
                  <CheckCircle2 className="w-3 h-3" />
                  ok
                </span>
              )}
            </div>
            <div className="text-xs text-slate-500 mt-0.5">
              {pendingCount > 0
                ? `${pendingCount} pendente${pendingCount > 1 ? 's' : ''} de confirmação — bloqueia${pendingCount > 1 ? 'm' : ''} o fechamento`
                : 'nenhuma variação anômala detectada'}
            </div>
          </div>
        </button>
        <div className="flex items-center gap-2">
          <label className="flex items-center gap-1 text-xs text-slate-600">
            <input
              type="checkbox"
              checked={showAll}
              onChange={e => setShowAll(e.target.checked)}
              className="w-3 h-3"
            />
            Mostrar tudo
          </label>
          {!isReadOnly && (
            <button
              type="button"
              onClick={handleRecheck}
              disabled={rechecking}
              className="inline-flex items-center gap-1 text-xs px-2 py-1 rounded border border-slate-200 text-slate-700 hover:bg-slate-50 disabled:opacity-50"
              title="Re-avaliar variações após edição manual de preços"
            >
              <RefreshCw className={`w-3 h-3 ${rechecking ? 'animate-spin' : ''}`} />
              Recalcular
            </button>
          )}
        </div>
      </div>

      {!collapsed && (
        <div className="overflow-x-auto">
          {displayRows.length === 0 ? (
            <div className="p-4 text-center text-sm text-slate-500">
              {showAll ? 'Nenhum item pra comparar.' : 'Nada a confirmar.'}
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-xs text-slate-600 uppercase tracking-wide">
                <tr>
                  <th className="text-left px-3 py-2 font-medium">Ativo</th>
                  <th className="text-left px-3 py-2 font-medium">Classe</th>
                  <th className="text-right px-3 py-2 font-medium">{prevLabel ?? 'Anterior'}</th>
                  <th className="text-right px-3 py-2 font-medium">Este mês</th>
                  <th className="text-right px-3 py-2 font-medium">Δ</th>
                  <th className="text-right px-3 py-2 font-medium">Δ %</th>
                  <th className="text-left px-3 py-2 font-medium">Status</th>
                  <th className="px-3 py-2" />
                </tr>
              </thead>
              <tbody>
                {displayRows.map(row => {
                  const badge = statusBadge(row.status)
                  const isPending = row.status === 'SUSPICIOUS_PENDING'
                  return (
                    <tr
                      key={row.asset_id}
                      className={`border-t border-slate-100 ${isPending ? 'bg-red-50/30' : ''}`}
                    >
                      <td className="px-3 py-2 whitespace-nowrap">
                        <div className="font-medium text-slate-800">{row.asset_name}</div>
                        {row.asset_ticker && (
                          <div className="text-xs text-slate-500">{row.asset_ticker}</div>
                        )}
                      </td>
                      <td className="px-3 py-2">
                        <ClassBadge klass={row.asset_class as any} />
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums">
                        {fmtMoney(row.previous_mv_native, row.currency)}
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums">
                        {fmtMoney(row.current_mv_native, row.currency)}
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums text-slate-700">
                        {fmtMoney(row.delta_native, row.currency)}
                      </td>
                      <td
                        className={`px-3 py-2 text-right tabular-nums font-medium ${
                          row.delta_pct != null && Number(row.delta_pct) >= Number(row.threshold_pct)
                            ? 'text-red-700'
                            : 'text-slate-700'
                        }`}
                      >
                        {fmtPct(row.delta_pct)}
                      </td>
                      <td className="px-3 py-2">
                        <span
                          className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded border text-xs ${badge.color}`}
                          title={`Threshold: ${(Number(row.threshold_pct) * 100).toFixed(0)}%`}
                        >
                          {badge.icon && <span>{badge.icon}</span>}
                          {STATUS_LABEL[row.status]}
                        </span>
                      </td>
                      <td className="px-3 py-2 text-right">
                        {isPending && !isReadOnly && (
                          <button
                            type="button"
                            onClick={() => handleConfirm(row)}
                            disabled={confirmingId === row.pendency_id}
                            className="inline-flex items-center gap-1 text-xs px-2 py-1 rounded bg-emerald-600 text-white hover:bg-emerald-700 disabled:opacity-50"
                          >
                            {confirmingId === row.pendency_id ? 'Confirmando…' : 'Confirmar'}
                          </button>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          )}
        </div>
      )}
    </Card>
  )
}
