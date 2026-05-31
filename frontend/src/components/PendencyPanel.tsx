/* Spec 35 — full pendency review panel.
 *
 * Shown on /snapshots/{id} when status === IN_REVIEW. Pendencies are
 * grouped by financial institution (sem instituição last) — that's how
 * the user normally goes through the closing (one statement per FI). */
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Edit2, RefreshCw, RotateCcw, Upload } from 'lucide-react'

import { api, type PendencyReason, type SnapshotPendencyOut } from '../lib/api'
import ExtractionUploadModal from './ExtractionUploadModal'

const REASON_META: Record<PendencyReason, { label: string; color: string }> = {
  API_FAILED:      { label: 'API falhou',     color: '#ef4444' },
  STALE_PRICE:     { label: 'Preço antigo',   color: '#f59e0b' },
  MANUAL_SOURCE:   { label: 'Manual',         color: '#3b82f6' },
  UPLOAD_REQUIRED: { label: 'Upload',         color: '#a855f7' },
}

const MONTH_NAMES = [
  'Jan', 'Fev', 'Mar', 'Abr', 'Mai', 'Jun',
  'Jul', 'Ago', 'Set', 'Out', 'Nov', 'Dez',
]

function ymShortLabel(periodEnd: string): string {
  // "2026-04-30" → "Abr/26"
  const [y, m] = periodEnd.split('-')
  return `${MONTH_NAMES[parseInt(m, 10) - 1]}/${y.slice(2)}`
}

function fmtBRL(n: number): string {
  return n.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })
}

const UNGROUPED_LABEL = 'Sem instituição'

function groupByInstitution(
  pendencies: SnapshotPendencyOut[],
): Array<{ name: string; items: SnapshotPendencyOut[] }> {
  const map = new Map<string, SnapshotPendencyOut[]>()
  for (const p of pendencies) {
    const k = p.asset_institution_short_name ?? UNGROUPED_LABEL
    if (!map.has(k)) map.set(k, [])
    map.get(k)!.push(p)
  }
  const groups = Array.from(map.entries())
    .map(([name, items]) => ({ name, items }))
    .sort((a, b) => {
      // ungrouped goes last; others alphabetical
      if (a.name === UNGROUPED_LABEL) return 1
      if (b.name === UNGROUPED_LABEL) return -1
      return a.name.localeCompare(b.name)
    })
  for (const g of groups) {
    g.items.sort((a, b) =>
      (a.asset_ticker ?? a.asset_name).localeCompare(b.asset_ticker ?? b.asset_name),
    )
  }
  return groups
}

interface Props {
  pendencies: SnapshotPendencyOut[]
  onResolved: () => void
  onConfirm?: () => void
}

export default function PendencyPanel({ pendencies, onResolved, onConfirm }: Props) {
  const open = pendencies.filter(p => !p.resolved_at)
  const closed = pendencies.length - open.length
  const allResolved = open.length === 0 && pendencies.length > 0
  const groups = useMemo(() => groupByInstitution(pendencies), [pendencies])

  return (
    <div className="rounded-xl bg-white dark:bg-gray-900 border border-amber-200 dark:border-amber-900 p-4 space-y-3">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-[12px] font-semibold text-gray-900 dark:text-gray-100">
            Pendências
          </div>
          <div className="text-[11px] text-gray-500 dark:text-gray-400">
            {closed} resolvidas · {open.length} abertas
          </div>
        </div>
        {onConfirm && (
          <button
            onClick={onConfirm}
            disabled={!allResolved}
            className="h-8 px-3 inline-flex items-center gap-1.5 rounded-lg text-[12px] bg-emerald-500 hover:bg-emerald-400 disabled:opacity-50 disabled:cursor-not-allowed text-white transition-colors"
            title={allResolved ? 'Fechar snapshot' : 'Resolva todas pendências antes de fechar'}
          >
            Confirmar fechamento
          </button>
        )}
      </div>

      {/* Progress */}
      <div className="h-1.5 w-full rounded-sm bg-gray-200 dark:bg-gray-800 overflow-hidden">
        <div
          className="h-full bg-emerald-500 transition-all"
          style={{ width: pendencies.length ? `${(closed / pendencies.length) * 100}%` : '0%' }}
        />
      </div>

      {pendencies.length === 0 ? (
        <div className="text-[11px] text-gray-500 dark:text-gray-400 py-2">
          Sem pendências — pode confirmar.
        </div>
      ) : (
        <div className="space-y-4 pt-2">
          {groups.map(g => {
            const groupOpen = g.items.filter(p => !p.resolved_at).length
            return (
              <div key={g.name} data-testid={`pendency-group-${g.name}`}>
                <div className="flex items-center justify-between mb-1.5">
                  <div className="text-[11px] font-semibold uppercase tracking-wider text-gray-700 dark:text-gray-300">
                    {g.name}
                  </div>
                  <div className="text-[10px] text-gray-500 dark:text-gray-400">
                    {groupOpen} de {g.items.length} abertas
                  </div>
                </div>
                <div className="space-y-2">
                  {g.items.map(p => (
                    <PendencyRow key={p.id} pendency={p} onResolved={onResolved} />
                  ))}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

function PendencyRow({
  pendency, onResolved,
}: { pendency: SnapshotPendencyOut; onResolved: () => void }) {
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [uploadOpen, setUploadOpen] = useState(false)
  const resolved = pendency.resolved_at != null
  const meta = REASON_META[pendency.reason]
  const prevPriceNum =
    pendency.previous_unit_price != null
      ? Number(pendency.previous_unit_price)
      : null
  const hasPrevious =
    prevPriceNum != null
    && Number.isFinite(prevPriceNum)
    && pendency.previous_period_end != null

  async function handleRetry() {
    setBusy(true); setErr(null)
    try {
      await api.retrySnapshotPendencyApi(pendency.id)
      onResolved()
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Erro')
    } finally {
      setBusy(false)
    }
  }

  async function handleRepeatPrevious() {
    if (!hasPrevious) return
    setBusy(true); setErr(null)
    try {
      await api.resolveSnapshotPendency(pendency.id, {
        new_price: pendency.previous_unit_price!,
        note: `copied from ${pendency.previous_period_end}`,
      })
      onResolved()
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Erro')
    } finally {
      setBusy(false)
    }
  }

  async function handleEdit() {
    // Minimal inline prompt — the full ManualPriceModal is spec-28 territory
    // and we don't have a clean way to inject it here without lifting state.
    const raw = window.prompt(
      `Novo preço para ${pendency.asset_ticker ?? pendency.asset_name}:`,
      hasPrevious ? prevPriceNum!.toFixed(2).replace('.', ',') : '',
    )
    if (!raw) return
    const normalized = raw.replace(/\./g, '').replace(',', '.').trim()
    const n = Number(normalized)
    if (!Number.isFinite(n) || n < 0) {
      setErr('Informe um número >= 0')
      return
    }
    setBusy(true); setErr(null)
    try {
      await api.resolveSnapshotPendency(pendency.id, { new_price: n.toFixed(2) })
      onResolved()
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Erro')
    } finally {
      setBusy(false)
    }
  }

  // Spec 38 — Upload button opens the LLM extraction modal. The legacy
  // "mark as resolved with a note" path stays available behind an explicit
  // user gesture (skip button inside the modal).

  return (
    <div
      className={`flex items-center gap-3 px-3 py-2 rounded-lg border ${
        resolved
          ? 'bg-emerald-50 dark:bg-emerald-900/10 border-emerald-200 dark:border-emerald-900'
          : 'bg-gray-50 dark:bg-gray-800/40 border-gray-200 dark:border-gray-800'
      }`}
      data-testid={`pendency-row-${pendency.id}`}
    >
      <span
        className="w-1 h-8 rounded-full shrink-0"
        style={{ background: meta.color }}
      />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <Link
            to={`/assets/${pendency.asset_id}`}
            className="text-[12px] font-mono font-medium text-gray-900 dark:text-gray-100 hover:text-indigo-500 dark:hover:text-indigo-300"
          >
            {pendency.asset_ticker ?? pendency.asset_name}
          </Link>
          <span
            className="inline-flex items-center px-1.5 py-px rounded text-[9px] font-semibold uppercase tracking-wider"
            style={{ background: meta.color + '26', color: meta.color }}
          >
            {meta.label}
          </span>
          {resolved && (
            <span className="text-[10px] text-emerald-600 dark:text-emerald-400">
              ✓ resolvido
            </span>
          )}
        </div>
        <div className="text-[10px] text-gray-500 dark:text-gray-400 truncate">
          {pendency.detail ?? pendency.asset_name}
          {hasPrevious && (
            <span className="ml-2 text-gray-600 dark:text-gray-300 tnum">
              · {ymShortLabel(pendency.previous_period_end!)}:{' '}
              {fmtBRL(prevPriceNum!)}
            </span>
          )}
        </div>
        {err && (
          <div className="text-[10px] text-red-500 dark:text-red-400 mt-0.5">{err}</div>
        )}
      </div>

      {!resolved && (
        <div className="flex items-center gap-1 shrink-0">
          {pendency.action_type === 'RETRY_API' && (
            <button
              onClick={handleRetry}
              disabled={busy}
              className="h-7 px-2 inline-flex items-center gap-1 rounded-md text-[11px] bg-indigo-500 hover:bg-indigo-400 disabled:opacity-50 text-white"
            >
              <RefreshCw className={`w-3 h-3 ${busy ? 'animate-spin' : ''}`} /> Retry
            </button>
          )}
          {pendency.action_type === 'EDIT_PRICE' && hasPrevious && (
            <button
              onClick={handleRepeatPrevious}
              disabled={busy}
              title={`Usar preço de ${ymShortLabel(pendency.previous_period_end!)}: ${fmtBRL(prevPriceNum!)}`}
              className="h-7 px-2 inline-flex items-center gap-1 rounded-md text-[11px] bg-indigo-500 hover:bg-indigo-400 disabled:opacity-50 text-white"
              data-testid={`pendency-repeat-${pendency.id}`}
            >
              <RotateCcw className="w-3 h-3" /> Repetir
            </button>
          )}
          {pendency.action_type === 'EDIT_PRICE' && (
            <button
              onClick={handleEdit}
              disabled={busy}
              className="h-7 px-2 inline-flex items-center gap-1 rounded-md text-[11px] border border-gray-300 dark:border-gray-700 hover:bg-gray-100 dark:hover:bg-gray-800 disabled:opacity-50"
            >
              <Edit2 className="w-3 h-3" /> Editar
            </button>
          )}
          {pendency.action_type === 'UPLOAD_FILE' && (
            <button
              onClick={() => setUploadOpen(true)}
              disabled={busy}
              className="h-7 px-2 inline-flex items-center gap-1 rounded-md text-[11px] border border-gray-300 dark:border-gray-700 hover:bg-gray-100 dark:hover:bg-gray-800 disabled:opacity-50"
              data-testid={`pendency-upload-${pendency.id}`}
            >
              <Upload className="w-3 h-3" /> Upload
            </button>
          )}
        </div>
      )}

      {uploadOpen && (
        <ExtractionUploadModal
          pendency={pendency}
          onResolved={onResolved}
          onClose={() => setUploadOpen(false)}
        />
      )}
    </div>
  )
}
