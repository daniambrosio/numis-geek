/* Spec 48 — Bulk extract upload zone.
 *
 * Rendered at the top of PendencyPanel when the snapshot is IN_REVIEW.
 * Supports drag-and-drop, click-to-pick AND cmd+V paste of clipboard
 * images. Each upload runs through:
 *   1. POST /attachments (source_type=snapshot, source_id=snapshot.id)
 *   2. POST /snapshots/{id}/bulk-extract  → ExtractionJob EXTRACTED
 *   3. Opens <BulkExtractReviewModal /> with the job
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { Sparkles, Upload as UploadIcon, X } from 'lucide-react'

import { api, type BulkExtractJobOut } from '../lib/api'

interface Props {
  snapshotId: string
  onJobReady: (job: BulkExtractJobOut) => void
}

type Phase = 'idle' | 'uploading' | 'error'

export default function BulkUploadZone({ snapshotId, onJobReady }: Props) {
  const [phase, setPhase] = useState<Phase>('idle')
  const [error, setError] = useState<string | null>(null)
  const [dragOver, setDragOver] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  const handleFile = useCallback(async (file: File) => {
    setError(null)
    setPhase('uploading')
    try {
      const att = await api.uploadAttachment('snapshot', snapshotId, file)
      const job = await api.createBulkExtract(snapshotId, att.id)
      if (job.status === 'FAILED') {
        setError(job.error_message ?? 'Extração falhou.')
        setPhase('error')
        return
      }
      setPhase('idle')
      onJobReady(job)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Erro no upload')
      setPhase('error')
    }
  }, [snapshotId, onJobReady])

  // cmd+V / ctrl+V — capturar imagem da clipboard. O listener vive enquanto
  // o componente está montado (ou seja: snapshot IN_REVIEW).
  useEffect(() => {
    function onPaste(e: ClipboardEvent) {
      if (phase === 'uploading') return
      const items = e.clipboardData?.items
      if (!items) return
      for (const item of items) {
        if (item.kind !== 'file') continue
        const file = item.getAsFile()
        if (!file) continue
        e.preventDefault()
        // Clipboard files often arrive nameless ("image.png").
        const named = file.name && file.name !== 'image.png'
          ? file
          : new File([file], `extrato-${Date.now()}.png`, { type: file.type || 'image/png' })
        void handleFile(named)
        return
      }
    }
    document.addEventListener('paste', onPaste)
    return () => document.removeEventListener('paste', onPaste)
  }, [handleFile, phase])

  function onDrop(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault()
    setDragOver(false)
    if (phase === 'uploading') return
    const f = e.dataTransfer.files?.[0]
    if (f) void handleFile(f)
  }

  function onPick(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0]
    if (f) void handleFile(f)
    e.target.value = ''
  }

  return (
    <div
      onDragOver={e => { e.preventDefault(); setDragOver(true) }}
      onDragLeave={() => setDragOver(false)}
      onDrop={onDrop}
      className={`mb-4 rounded-lg border-2 border-dashed px-4 py-4 transition-colors ${
        dragOver
          ? 'border-indigo-500 bg-indigo-500/[0.06]'
          : 'border-amber-500/40 bg-amber-500/[0.02] hover:border-amber-500/60'
      }`}
      data-testid="bulk-upload-zone"
    >
      <div className="flex items-center gap-3">
        <div className="shrink-0 w-10 h-10 rounded-lg bg-amber-500/15 flex items-center justify-center">
          <UploadIcon className="w-4 h-4 text-amber-600 dark:text-amber-400" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-[13px] font-semibold text-gray-900 dark:text-gray-100 flex items-center gap-2">
            Carregar extrato
            <span className="text-[10px] text-indigo-600 dark:text-indigo-400 inline-flex items-center gap-1">
              <Sparkles className="w-3 h-3" /> LLM
            </span>
          </div>
          <div className="text-[11px] text-gray-500">
            Arraste, clique pra escolher, ou cole (cmd+V) um screenshot.
            O sistema lê a lista de ativos e fecha múltiplas pendências de uma vez.
          </div>
        </div>
        <button
          onClick={() => fileRef.current?.click()}
          disabled={phase === 'uploading'}
          className="shrink-0 h-8 px-3 inline-flex items-center gap-1.5 rounded-lg text-[12px] bg-indigo-500 hover:bg-indigo-400 disabled:opacity-50 text-white"
          data-testid="bulk-upload-pick"
        >
          {phase === 'uploading' ? 'Extraindo…' : 'Escolher arquivo'}
        </button>
        <input
          ref={fileRef}
          type="file"
          accept="image/*,application/pdf,.csv,.xlsx"
          className="hidden"
          onChange={onPick}
        />
      </div>
      {error && (
        <div className="mt-2 flex items-start gap-2 text-[11px] text-red-600 dark:text-red-400" data-testid="bulk-upload-error">
          <X className="w-3 h-3 mt-0.5 shrink-0" />
          <span>{error}</span>
        </div>
      )}
    </div>
  )
}
