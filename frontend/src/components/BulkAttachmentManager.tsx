/* Spec 49 — Persistent attachment manager for snapshot bulk extraction.
 *
 * Replaces the Spec 48 BulkUploadZone. Architecture:
 *   - Dropzone (drag/click/paste) uploads attachment only — no LLM trigger.
 *   - Below it, a list of uploaded attachments persisted in the DB
 *     (source_type=snapshot). Each row carries the matching ExtractionJob's
 *     state and exposes Preview / Extract / Re-extract / Remove actions.
 *   - Sequential queue: while one extraction runs, other Extract buttons
 *     disable and show "Aguardando". */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Eye, FileText, Image as ImageIcon, Loader2, Sparkles, Trash2,
  Upload as UploadIcon, X,
} from 'lucide-react'

import {
  api,
  getToken,
  type AttachmentKind,
  type AttachmentOut,
  type BulkExtractJobOut,
  type BulkExtractionJobSummary,
  type SnapshotPendencyOut,
} from '../lib/api'
import BulkExtractReviewModal from './BulkExtractReviewModal'
import BulkIncomeReviewModal from './BulkIncomeReviewModal'

interface Props {
  snapshotId: string
  pendencies: SnapshotPendencyOut[]
  onResolved: () => void
  /**
   * Spec 58 — when set, the manager scopes uploads + listings to this FI.
   * Uploads auto-trigger extraction with institution_id, and only jobs
   * tagged with this FI are listed. When null/undefined, falls back to
   * the legacy per-snapshot behavior.
   */
  institutionId?: string | null
  /**
   * Spec 58 Stage 4 — what the upload is for:
   *  - 'positions' (default): updates Asset prices, resolves pendencies.
   *  - 'income': creates Distribution rows (dividendos, juros, aluguel).
   * Scoped per-FI via `institutionId`. Required to be 'positions' when
   * `institutionId` is null (legacy bucket).
   */
  purpose?: 'positions' | 'income'
}

function fmtSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function KindIcon({ kind }: { kind: AttachmentKind }) {
  if (kind === 'image') return <ImageIcon className="w-3.5 h-3.5" />
  return <FileText className="w-3.5 h-3.5" />
}

export default function BulkAttachmentManager({
  snapshotId, pendencies, onResolved, institutionId, purpose = 'positions',
}: Props) {
  const isIncome = purpose === 'income'
  const [attachments, setAttachments] = useState<AttachmentOut[]>([])
  const [jobs, setJobs] = useState<BulkExtractionJobSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [uploading, setUploading] = useState(false)
  const [extractingId, setExtractingId] = useState<string | null>(null)
  const [reviewJob, setReviewJob] = useState<BulkExtractJobOut | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [dragOver, setDragOver] = useState(false)
  const [deletingIds, setDeletingIds] = useState<Set<string>>(new Set())
  const fileRef = useRef<HTMLInputElement>(null)

  const refresh = useCallback(async () => {
    try {
      const [as_, js] = await Promise.all([
        api.listSnapshotAttachments(snapshotId),
        api.listSnapshotExtractions(snapshotId),
      ])
      setAttachments(as_)
      setJobs(js)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Erro carregando anexos')
    } finally {
      setLoading(false)
    }
  }, [snapshotId])

  useEffect(() => { void refresh() }, [refresh])

  // Pick the latest job per attachment (newest by created_at). When
  // scoped to a FI, only consider jobs at that FI — otherwise an
  // attachment extracted twice (once per FI) would show the wrong job.
  // Spec 58 Stage 4: also filter by source_hint so the Income manager
  // doesn't list Positions jobs (and vice-versa).
  const expectedHint = isIncome ? 'BROKER_INCOME' : 'BROKER_POSITION'
  const jobByAttachmentId = useMemo(() => {
    const m = new Map<string, BulkExtractionJobSummary>()
    for (const j of jobs) {
      if (institutionId && j.institution_id !== institutionId) continue
      if (institutionId && j.source_hint !== expectedHint) continue
      const prev = m.get(j.attachment_id)
      if (!prev || j.created_at > prev.created_at) m.set(j.attachment_id, j)
    }
    return m
  }, [jobs, institutionId, expectedHint])

  // Spec 58 — only show attachments with a job at this FI when scoped.
  // Otherwise per-FI groups would all show the same global attachment list.
  // Legacy unscoped mode (institutionId=null) shows everything.
  const visibleAttachments = useMemo(() => {
    if (!institutionId) return attachments
    return attachments.filter(att => jobByAttachmentId.has(att.id))
  }, [attachments, jobByAttachmentId, institutionId])

  const handleFile = useCallback(async (file: File) => {
    setError(null)
    setUploading(true)
    try {
      const att = await api.uploadAttachment('snapshot', snapshotId, file)
      await refresh()
      // Spec 58 — when scoped to a FI, the upload point also implies
      // "extract under this FI". Auto-trigger so the user lands in the
      // review modal in one step instead of two clicks.
      if (institutionId) {
        setExtractingId(att.id)
        try {
          const job = isIncome
            ? await api.createBulkIncomeForFI(snapshotId, institutionId, att.id)
            : await api.createBulkExtractForFI(snapshotId, institutionId, att.id)
          await refresh()
          if (job.status === 'EXTRACTED') setReviewJob(job)
          else if (job.status === 'FAILED') {
            setError(job.error_message ?? 'Extração falhou.')
          }
        } finally {
          setExtractingId(null)
        }
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Erro no upload')
    } finally {
      setUploading(false)
    }
  }, [snapshotId, refresh, institutionId, isIncome])

  // cmd+V paste handler.
  useEffect(() => {
    function onPaste(e: ClipboardEvent) {
      if (uploading || extractingId) return
      const items = e.clipboardData?.items
      if (!items) return
      for (const item of items) {
        if (item.kind !== 'file') continue
        const file = item.getAsFile()
        if (!file) continue
        e.preventDefault()
        const named = file.name && file.name !== 'image.png'
          ? file
          : new File([file], `extrato-${Date.now()}.png`, { type: file.type || 'image/png' })
        void handleFile(named)
        return
      }
    }
    document.addEventListener('paste', onPaste)
    return () => document.removeEventListener('paste', onPaste)
  }, [handleFile, uploading, extractingId])

  async function handleExtract(attachmentId: string) {
    setError(null)
    setExtractingId(attachmentId)
    try {
      const job = institutionId
        ? (isIncome
            ? await api.createBulkIncomeForFI(snapshotId, institutionId, attachmentId)
            : await api.createBulkExtractForFI(snapshotId, institutionId, attachmentId))
        : await api.createBulkExtract(snapshotId, attachmentId)
      await refresh()
      if (job.status === 'EXTRACTED') {
        setReviewJob(job)
      } else if (job.status === 'FAILED') {
        setError(job.error_message ?? 'Extração falhou.')
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Erro')
    } finally {
      setExtractingId(null)
    }
  }

  async function handleRevisar(jobId: string) {
    // Re-fetch the full extracted_json (the list endpoint only carries summary).
    setError(null)
    try {
      const full = await api.getExtraction(jobId)
      // Spec 58 — pick FI from the job summary we already loaded.
      const summary = jobs.find(j => j.id === jobId)
      setReviewJob({
        id: full.id,
        status: full.status,
        extracted_json: full.extracted_json,
        error_message: full.error_message,
        institution_id: summary?.institution_id ?? null,
        institution_short_name: summary?.institution_short_name ?? null,
      })
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Erro')
    }
  }

  async function handleRemove(attachmentId: string) {
    if (deletingIds.has(attachmentId)) return
    setError(null)
    setDeletingIds(prev => {
      const next = new Set(prev); next.add(attachmentId); return next
    })
    try {
      await api.deleteAttachment(attachmentId)
      await refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Erro ao remover anexo')
    } finally {
      setDeletingIds(prev => {
        const next = new Set(prev); next.delete(attachmentId); return next
      })
    }
  }

  async function handlePreview(att: AttachmentOut) {
    // /download requires Bearer auth — fetch as blob and open the
    // resulting object URL so the browser previews PNG/PDF inline.
    setError(null)
    try {
      const token = getToken()
      const r = await fetch(`/api/attachments/${att.id}/download`, {
        headers: token ? { Authorization: `Bearer ${token}` } : undefined,
      })
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      const blob = await r.blob()
      const url = URL.createObjectURL(blob)
      window.open(url, '_blank')
      // Revoke after a delay so the new tab has time to load.
      setTimeout(() => URL.revokeObjectURL(url), 60_000)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Erro abrindo preview')
    }
  }

  function onDrop(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault()
    setDragOver(false)
    if (uploading) return
    const f = e.dataTransfer.files?.[0]
    if (f) void handleFile(f)
  }

  function onPick(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0]
    if (f) void handleFile(f)
    e.target.value = ''
  }

  return (
    <div className="rounded-lg border border-amber-500/30 bg-amber-500/[0.02] p-3 space-y-2.5" data-testid="bulk-manager">
      <div className="flex items-center gap-2">
        <UploadIcon className="w-3.5 h-3.5 text-amber-600 dark:text-amber-400" />
        <h4 className="text-[12px] font-semibold text-gray-900 dark:text-gray-100">
          {isIncome ? 'Proventos do mês' : 'Posições do mês'}
        </h4>
        <span className="text-[10px] text-indigo-600 dark:text-indigo-400 inline-flex items-center gap-1 ml-1">
          <Sparkles className="w-3 h-3" />
          {isIncome ? 'cria Distribution rows' : 'atualiza preços'}
        </span>
      </div>

      <div
        onDragOver={e => { e.preventDefault(); setDragOver(true) }}
        onDragLeave={() => setDragOver(false)}
        onDrop={onDrop}
        className={`rounded-md border-2 border-dashed px-3 py-2.5 transition-colors ${
          dragOver
            ? 'border-indigo-500 bg-indigo-500/[0.06]'
            : 'border-amber-500/40 bg-white/40 dark:bg-gray-900/30 hover:border-amber-500/60'
        }`}
        data-testid="bulk-upload-dropzone"
      >
        <div className="flex items-center gap-3">
          <div className="flex-1 text-[11px] text-gray-500">
            Arraste, clique, ou cole (cmd+V) prints ou PDFs.
            Cada anexo fica salvo; clique <strong>Extrair</strong> quando quiser processar.
          </div>
          <button
            onClick={() => fileRef.current?.click()}
            disabled={uploading}
            className="shrink-0 h-7 px-2.5 inline-flex items-center gap-1.5 rounded-md text-[11px] bg-indigo-500 hover:bg-indigo-400 disabled:opacity-50 text-white"
            data-testid="bulk-upload-pick"
          >
            {uploading ? <Loader2 className="w-3 h-3 animate-spin" /> : <UploadIcon className="w-3 h-3" />}
            {uploading ? 'Carregando…' : 'Escolher'}
          </button>
          <input
            ref={fileRef}
            type="file"
            accept="image/*,application/pdf,.csv,.xlsx"
            className="hidden"
            onChange={onPick}
          />
        </div>
      </div>

      {error && (
        <div className="flex items-start gap-2 text-[11px] text-red-600 dark:text-red-400" data-testid="bulk-manager-error">
          <X className="w-3 h-3 mt-0.5 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* Attachment list */}
      {!loading && visibleAttachments.length === 0 ? (
        <div className="text-[11px] text-gray-500 italic py-1">
          Nenhum anexo subido ainda.
        </div>
      ) : (
        <ul className="space-y-1.5">
          {visibleAttachments.map(att => {
            const job = jobByAttachmentId.get(att.id) ?? null
            return (
              <AttachmentRow
                key={att.id}
                att={att}
                job={job}
                otherRunning={extractingId !== null && extractingId !== att.id}
                meRunning={extractingId === att.id}
                deleting={deletingIds.has(att.id)}
                onPreview={() => handlePreview(att)}
                onExtract={() => handleExtract(att.id)}
                onReview={(jobId) => handleRevisar(jobId)}
                onRemove={() => handleRemove(att.id)}
              />
            )
          })}
        </ul>
      )}

      {reviewJob && (isIncome ? (
        <BulkIncomeReviewModal
          job={reviewJob}
          onApplied={() => {
            setReviewJob(null)
            void refresh()
            onResolved()
          }}
          onClose={() => setReviewJob(null)}
        />
      ) : (
        <BulkExtractReviewModal
          job={reviewJob}
          pendencies={pendencies}
          onApplied={() => {
            setReviewJob(null)
            void refresh()
            onResolved()
          }}
          onClose={() => setReviewJob(null)}
        />
      ))}
    </div>
  )
}

function statusBadge(
  job: BulkExtractionJobSummary | null,
  meRunning: boolean,
): { label: string; color: string } | null {
  if (meRunning || (job && (job.status === 'PENDING' || job.status === 'RUNNING'))) {
    return { label: 'Extraindo…', color: 'bg-indigo-500/15 text-indigo-600 dark:text-indigo-300' }
  }
  if (!job) return null
  if (job.status === 'EXTRACTED') {
    return {
      label: `✨ ${job.positions_count} posiç${job.positions_count === 1 ? 'ão' : 'ões'}`,
      color: 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300',
    }
  }
  if (job.status === 'CONFIRMED') {
    return { label: '✓ Aplicado', color: 'bg-emerald-600 text-white' }
  }
  if (job.status === 'FAILED') {
    return { label: '⚠ Falhou', color: 'bg-red-500/15 text-red-600 dark:text-red-400' }
  }
  if (job.status === 'REJECTED') {
    return { label: '⊘ Descartado', color: 'bg-gray-500/15 text-gray-500' }
  }
  return null
}

function AttachmentRow({
  att, job, otherRunning, meRunning, deleting,
  onPreview, onExtract, onReview, onRemove,
}: {
  att: AttachmentOut
  job: BulkExtractionJobSummary | null
  otherRunning: boolean
  meRunning: boolean
  deleting?: boolean
  onPreview: () => void
  onExtract: () => void
  onReview: (jobId: string) => void
  onRemove: () => void
}) {
  const badge = statusBadge(job, meRunning)
  const isExtracting = meRunning || (job?.status === 'RUNNING' || job?.status === 'PENDING')
  const canRemove = !isExtracting && job?.status !== 'CONFIRMED' && !deleting

  return (
    <li
      className={`flex items-center gap-2.5 px-2 py-1.5 rounded-md border bg-white dark:bg-gray-900 transition-colors ${
        deleting
          ? 'border-red-500/40 bg-red-500/[0.04] opacity-60 pointer-events-none'
          : 'border-gray-200 dark:border-gray-800'
      }`}
      data-testid={`attachment-row-${att.id}`}
    >
      <div className="w-7 h-7 rounded-md flex items-center justify-center shrink-0 bg-indigo-500/15 text-indigo-600 dark:text-indigo-300">
        <KindIcon kind={att.kind} />
      </div>
      <div className="flex-1 min-w-0">
        <div className="text-[12px] font-medium truncate text-gray-900 dark:text-gray-100">{att.filename}</div>
        <div className="text-[10px] text-gray-500 tnum flex items-center gap-1.5">
          {deleting ? (
            <>
              <Loader2 className="w-3 h-3 animate-spin text-red-400" />
              <span className="text-red-400">removendo…</span>
            </>
          ) : (
            <>
          {fmtSize(att.size_bytes)}
          {badge && (
            <span className={`ml-2 px-1.5 py-0.5 rounded text-[9px] font-semibold uppercase tracking-wider ${badge.color}`}>
              {badge.label}
            </span>
          )}
          {job && job.cost_usd && parseFloat(job.cost_usd) > 0 && (
            <span
              className="ml-2 text-[10px] text-gray-500 tnum"
              title={`Modelo: ${job.model ?? '—'} · ${job.input_tokens ?? 0} in · ${job.output_tokens ?? 0} out`}
            >
              ${parseFloat(job.cost_usd).toFixed(4)}
              {(job.input_tokens != null || job.output_tokens != null) && (
                <> · {(job.input_tokens ?? 0) + (job.output_tokens ?? 0)} toks</>
              )}
            </span>
          )}
          {job?.error_message && (
            <span className="ml-2 text-[10px] text-red-500" title={job.error_message}>
              {job.error_message.slice(0, 60)}…
            </span>
          )}
            </>
          )}
        </div>
      </div>
      <div className="flex items-center gap-1 shrink-0">
        <button
          onClick={onPreview}
          className="h-7 px-2 inline-flex items-center gap-1 rounded-md text-[11px] bg-gray-100 dark:bg-gray-800 hover:bg-gray-200 dark:hover:bg-gray-700 text-gray-700 dark:text-gray-300"
          title="Abrir em nova aba"
        >
          <Eye className="w-3 h-3" />
        </button>
        {job?.status === 'EXTRACTED' ? (
          <button
            onClick={() => onReview(job.id)}
            disabled={otherRunning}
            className="h-7 px-2.5 inline-flex items-center gap-1 rounded-md text-[11px] bg-emerald-500 hover:bg-emerald-400 disabled:opacity-50 text-white"
            data-testid={`attachment-review-${att.id}`}
          >
            Revisar
          </button>
        ) : null}
        {(!job || job.status === 'FAILED' || job.status === 'REJECTED' || job.status === 'EXTRACTED' || job.status === 'CONFIRMED') && (() => {
          const isReExtract = job?.status === 'EXTRACTED' || job?.status === 'CONFIRMED'
          const baseLabel = isReExtract ? 'Re-extrair' : 'Extrair'
          const label = meRunning ? 'Extraindo…' : baseLabel
          return (
            <button
              onClick={onExtract}
              disabled={otherRunning || meRunning}
              title={
                otherRunning && !meRunning
                  ? 'Outra extração em andamento — aguarde'
                  : (isReExtract ? 'Re-extrair (sobrescreve a extração anterior)' : 'Extrair')
              }
              className={`h-7 px-2.5 inline-flex items-center gap-1 rounded-md text-[11px] ${
                isReExtract
                  ? 'border border-gray-300 dark:border-gray-700 text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800'
                  : 'bg-indigo-500 hover:bg-indigo-400 text-white'
              } disabled:opacity-50 disabled:cursor-not-allowed`}
              data-testid={`attachment-extract-${att.id}`}
            >
              {meRunning && <Loader2 className="w-3 h-3 animate-spin" />}
              {label}
            </button>
          )
        })()}
        <button
          onClick={onRemove}
          disabled={!canRemove}
          title={canRemove ? 'Remover anexo' : 'Não dá pra remover (extração aplicada ou em curso)'}
          className="h-7 w-7 inline-flex items-center justify-center rounded-md text-gray-400 hover:text-red-400 hover:bg-red-500/10 disabled:opacity-30 disabled:cursor-not-allowed"
          data-testid={`attachment-remove-${att.id}`}
        >
          <Trash2 className="w-3 h-3" />
        </button>
      </div>
    </li>
  )
}
