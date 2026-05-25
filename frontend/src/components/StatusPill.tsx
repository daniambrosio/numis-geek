/* Spec 35 — snapshot status pill (SCHEDULED / IN_REVIEW / CLOSED). */
import type { SnapshotStatus } from '../lib/api'

const STATUS_META: Record<SnapshotStatus, { label: string; cls: string }> = {
  SCHEDULED: {
    label: 'Agendado',
    cls: 'bg-slate-500/15 text-slate-600 dark:text-slate-300',
  },
  IN_REVIEW: {
    label: 'Em revisão',
    cls: 'bg-amber-500/15 text-amber-700 dark:text-amber-400',
  },
  CLOSED: {
    label: 'Fechado',
    cls: 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-400',
  },
}

export default function StatusPill({ status }: { status: SnapshotStatus }) {
  const m = STATUS_META[status]
  return (
    <span
      className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wider ${m.cls}`}
      data-testid={`status-pill-${status}`}
    >
      {m.label}
    </span>
  )
}
