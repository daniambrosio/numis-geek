/* Spec 51 — Retroactive Event Reconciliation.
 *
 * Disparado depois de salvar um evento retroativo (movement, corp
 * action) que altera a posição passada de um ativo. Lista os
 * fechamentos afetados com delta antes/depois e 3 ações:
 * - Cancelar (ESC/X/botão): fecha sem efeito; sem audit
 * - Manter divergência: exige reason, grava no audit log
 * - Aplicar: recomputa cada item marcado (auto-reopen CLOSED) */
import { useEffect, useState } from 'react'
import { AlertTriangle, X } from 'lucide-react'

import { api, type AffectedSnapshotOut } from '../lib/api'
import { useEscapeKey } from '../lib/useEscapeKey'

interface Props {
  assetId: string
  assetLabel?: string        // ticker/nome para o cabeçalho
  affected: AffectedSnapshotOut[]
  triggerEventType: string
  triggerEventId: string
  onClose: () => void        // cancel — sem efeito
  onApplied: () => void      // todos marcados aplicados
  onSkipped: () => void      // todos marcados skipados
}

function fmtBRL(s: string | null): string {
  if (s == null) return '—'
  const n = Number(s)
  if (!Number.isFinite(n)) return '—'
  return n.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })
}

function fmtQty(s: string): string {
  const n = Number(s)
  if (!Number.isFinite(n)) return s
  return n.toLocaleString('pt-BR', {
    minimumFractionDigits: 0,
    maximumFractionDigits: 4,
  })
}

const PT_MONTHS = [
  'Jan', 'Fev', 'Mar', 'Abr', 'Mai', 'Jun',
  'Jul', 'Ago', 'Set', 'Out', 'Nov', 'Dez',
]

function fmtYm(ym: string): string {
  const [y, m] = ym.split('-')
  return `${PT_MONTHS[parseInt(m, 10) - 1] ?? m}/${y.slice(2)}`
}

export default function AffectedSnapshotsModal({
  assetId, assetLabel, affected, triggerEventType, triggerEventId,
  onClose, onApplied, onSkipped,
}: Props) {
  useEscapeKey(onClose)

  // Cada snapshot tem um checkbox; default = todos marcados.
  const [selected, setSelected] = useState<Set<string>>(
    () => new Set(affected.map(a => a.snapshot_id)),
  )
  const [phase, setPhase] = useState<'choose' | 'skipReason' | 'busy'>('choose')
  const [skipReason, setSkipReason] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const [progress, setProgress] = useState(0)

  useEffect(() => {
    setSelected(new Set(affected.map(a => a.snapshot_id)))
  }, [affected])

  function toggle(id: string) {
    setSelected(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id); else next.add(id)
      return next
    })
  }

  function toggleAll() {
    setSelected(prev =>
      prev.size === affected.length
        ? new Set()
        : new Set(affected.map(a => a.snapshot_id)),
    )
  }

  async function handleApply() {
    if (selected.size === 0) { onClose(); return }
    setPhase('busy'); setErr(null); setProgress(0)
    try {
      const targets = affected.filter(a => selected.has(a.snapshot_id))
      for (let i = 0; i < targets.length; i++) {
        await api.recomputeSnapshotItem(
          targets[i].snapshot_id, assetId,
          { trigger_event_type: triggerEventType, trigger_event_id: triggerEventId },
        )
        setProgress(i + 1)
      }
      onApplied()
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Erro')
      setPhase('choose')
    }
  }

  async function handleSkipSubmit() {
    if (selected.size === 0 || !skipReason.trim()) return
    setPhase('busy'); setErr(null); setProgress(0)
    try {
      const targets = affected.filter(a => selected.has(a.snapshot_id))
      for (let i = 0; i < targets.length; i++) {
        await api.skipRecomputeSnapshotItem(
          targets[i].snapshot_id, assetId,
          {
            trigger_event_type: triggerEventType,
            trigger_event_id: triggerEventId,
            reason: skipReason.trim(),
          },
        )
        setProgress(i + 1)
      }
      onSkipped()
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Erro')
      setPhase('skipReason')
    }
  }

  const hasClosed = affected.some(a => a.status === 'CLOSED')
  const targetCount = selected.size

  return (
    <div
      className="fixed inset-0 z-[70] flex items-center justify-center bg-black/60 p-4"
      onClick={phase === 'busy' ? undefined : onClose}
      role="dialog"
      aria-modal="true"
    >
      <div
        className="w-full max-w-2xl bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-700 shadow-2xl flex flex-col max-h-[90vh]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="px-5 py-3 border-b border-gray-200 dark:border-gray-800 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <AlertTriangle className="w-4 h-4 text-amber-500" />
            <div className="text-sm font-semibold">Impacto em fechamentos</div>
          </div>
          <button
            onClick={onClose}
            disabled={phase === 'busy'}
            className="w-7 h-7 inline-flex items-center justify-center rounded-md text-gray-400 hover:text-gray-700 dark:hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800 disabled:opacity-50"
            aria-label="Fechar"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="p-5 space-y-3 overflow-y-auto">
          <div className="text-[12px] text-gray-600 dark:text-gray-400">
            Esse lançamento afeta{' '}
            <strong>{affected.length} fechamento{affected.length === 1 ? '' : 's'}</strong>
            {assetLabel ? <> de <strong>{assetLabel}</strong></> : null}.
            {hasClosed && (
              <> Snapshots <strong>CLOSED</strong> serão reabertos automaticamente.</>
            )}
          </div>

          <div className="overflow-x-auto -mx-1">
            <table className="w-full text-[12px]" data-testid="affected-snapshots-table">
              <thead>
                <tr className="text-[10px] uppercase tracking-wider text-gray-500 border-b border-gray-200 dark:border-gray-800">
                  <th className="text-left py-2 px-2 w-8">
                    <input
                      type="checkbox"
                      checked={selected.size === affected.length}
                      onChange={toggleAll}
                      disabled={phase !== 'choose'}
                    />
                  </th>
                  <th className="text-left py-2 px-2">Período</th>
                  <th className="text-left py-2 px-2">Status</th>
                  <th className="text-right py-2 px-2">Qtd ativo antes → depois</th>
                  <th className="text-right py-2 px-2">Valor ativo (BRL)</th>
                  <th className="text-right py-2 px-2">Patrimônio total do mês</th>
                </tr>
              </thead>
              <tbody>
                {affected.map(a => {
                  const qtyChanged = a.old_quantity !== a.new_quantity
                  const oldMv = a.old_market_value_brl
                  const newMv = a.new_market_value_brl
                  const mvChanged = oldMv !== newMv
                  // Patrimônio total do mês antes/depois — soma do item
                  // delta no header total. Frontend calcula (backend
                  // só envia "antes"; "depois" sai aqui).
                  const totalBefore = Number(a.snapshot_total_value_brl)
                  const delta = (Number(newMv ?? 0)) - (Number(oldMv ?? 0))
                  const totalAfter = totalBefore + delta
                  return (
                    <tr
                      key={a.snapshot_id}
                      className="border-b border-gray-100 dark:border-gray-800/60"
                    >
                      <td className="px-2 py-2">
                        <input
                          type="checkbox"
                          checked={selected.has(a.snapshot_id)}
                          onChange={() => toggle(a.snapshot_id)}
                          disabled={phase !== 'choose'}
                          data-testid={`affected-snapshot-check-${a.ym}`}
                        />
                      </td>
                      <td className="px-2 py-2 font-medium">{fmtYm(a.ym)}</td>
                      <td className="px-2 py-2">
                        <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] uppercase tracking-wider ${
                          a.status === 'CLOSED'
                            ? 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-400'
                            : 'bg-amber-500/15 text-amber-700 dark:text-amber-400'
                        }`}>
                          {a.status}
                        </span>
                      </td>
                      <td className="px-2 py-2 text-right tnum">
                        <span className="text-gray-500">{fmtQty(a.old_quantity)}</span>
                        <span className="mx-1 text-gray-400">→</span>
                        <span className={qtyChanged ? 'text-gray-900 dark:text-white font-medium' : 'text-gray-500'}>
                          {fmtQty(a.new_quantity)}
                        </span>
                      </td>
                      <td className="px-2 py-2 text-right tnum">
                        <span className="text-gray-500">{fmtBRL(oldMv)}</span>
                        <span className="mx-1 text-gray-400">→</span>
                        <span className={mvChanged ? 'text-gray-900 dark:text-white font-medium' : 'text-gray-500'}>
                          {fmtBRL(newMv)}
                        </span>
                      </td>
                      <td className="px-2 py-2 text-right tnum text-[11px]">
                        <div className="text-gray-500">{fmtBRL(String(totalBefore))}</div>
                        <div className={`font-semibold ${delta > 0 ? 'text-emerald-500 dark:text-emerald-400' : delta < 0 ? 'text-red-500 dark:text-red-400' : 'text-gray-500'}`}>
                          → {fmtBRL(String(totalAfter))}
                          {delta !== 0 && (
                            <span className="ml-1 text-[10px]">
                              ({delta > 0 ? '+' : ''}{fmtBRL(String(delta))})
                            </span>
                          )}
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>

          {phase === 'skipReason' && (
            <div className="rounded-lg border border-amber-300 dark:border-amber-700 bg-amber-50 dark:bg-amber-900/10 p-3 space-y-2">
              <div className="text-[11px] font-semibold text-amber-800 dark:text-amber-300">
                Confirmar "Não atualizar fechamento"
              </div>
              <div className="text-[11px] text-amber-700 dark:text-amber-400">
                {targetCount === 1 ? 'O fechamento marcado' : `Os ${targetCount} fechamentos marcados`} fica{targetCount === 1 ? '' : 'm'} congelado{targetCount === 1 ? '' : 's'} — patrimônio total não muda. A nota fica registrada no audit log.
              </div>
              <textarea
                value={skipReason}
                onChange={e => setSkipReason(e.target.value)}
                placeholder="Por quê manter a divergência?"
                rows={2}
                className="w-full text-[12px] p-2 rounded border border-amber-200 dark:border-amber-800 bg-white dark:bg-gray-900 focus:outline-none focus:border-amber-500"
                data-testid="skip-reason-input"
              />
            </div>
          )}

          {phase === 'busy' && (
            <div className="text-[12px] text-gray-500" data-testid="affected-busy">
              {progress < targetCount ? `Aplicando ${progress + 1}/${targetCount}…` : 'Finalizando…'}
            </div>
          )}

          {err && (
            <div className="text-[11px] text-red-600 dark:text-red-400">{err}</div>
          )}
        </div>

        <div className="px-5 py-3 border-t border-gray-200 dark:border-gray-800 flex items-center justify-between gap-2">
          <button
            onClick={onClose}
            disabled={phase === 'busy'}
            className="h-8 px-3 inline-flex items-center gap-1.5 rounded-lg text-[12px] bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700 disabled:opacity-50"
          >
            Cancelar
          </button>
          <div className="flex items-center gap-2">
            {phase === 'choose' && (
              <>
                <button
                  onClick={() => setPhase('skipReason')}
                  disabled={selected.size === 0}
                  title="Snapshot fica congelado como está — totals NÃO são recalculados. Útil pra fechamentos já reportados ao IR."
                  className="h-8 px-3 inline-flex flex-col items-center justify-center gap-0 rounded-lg border border-amber-300 dark:border-amber-700 text-amber-700 dark:text-amber-400 hover:bg-amber-50 dark:hover:bg-amber-900/20 disabled:opacity-50"
                  data-testid="affected-snapshots-skip"
                >
                  <span className="text-[12px] leading-none">Não atualizar fechamento</span>
                  <span className="text-[9px] leading-none mt-0.5 opacity-80">snapshot fica congelado</span>
                </button>
                <button
                  onClick={() => void handleApply()}
                  disabled={selected.size === 0}
                  title="Recomputa o item e atualiza o patrimônio total do snapshot."
                  className="h-9 px-4 inline-flex flex-col items-center justify-center gap-0 rounded-lg font-medium bg-indigo-500 hover:bg-indigo-400 disabled:opacity-50 disabled:cursor-not-allowed text-white"
                  data-testid="affected-snapshots-apply"
                >
                  <span className="text-[13px] leading-none">Atualizar fechamento{selected.size > 1 ? ` (${selected.size})` : ''}</span>
                  <span className="text-[9px] leading-none mt-0.5 opacity-80">totals serão recalculados</span>
                </button>
              </>
            )}
            {phase === 'skipReason' && (
              <>
                <button
                  onClick={() => setPhase('choose')}
                  className="h-8 px-3 inline-flex items-center gap-1.5 rounded-lg text-[12px] text-gray-500 hover:text-gray-700"
                >
                  Voltar
                </button>
                <button
                  onClick={() => void handleSkipSubmit()}
                  disabled={!skipReason.trim()}
                  className="h-9 px-4 inline-flex items-center gap-1.5 rounded-lg text-[13px] font-medium bg-amber-500 hover:bg-amber-400 disabled:opacity-50 text-white"
                  data-testid="affected-snapshots-skip-confirm"
                >
                  Confirmar
                </button>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
