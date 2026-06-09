/* Spec 37 — "Notas & documentos" card shown inside detail panels (Lançamento,
   Provento, Ativo). Mirrors the prototype's `NotesAttachments` component
   (index.html:4168) — distinct from `NotesAttachmentsField` which lives
   inside the composers and works with drafts. Here the row already exists,
   so uploads/deletes hit the API immediately.

   Behavior:
   - Notes textarea — debounced auto-save (~800 ms after last keystroke).
   - Persisted attachments — list with download + delete per row.
   - Drop zone — paste / drag / click; uploads via Spec 19 `POST /attachments`.
*/
import { useEffect, useRef, useState } from 'react'
import { Download, Trash2, Paperclip, FileText, Image as ImageIcon, FileSpreadsheet, File as FileIcon, Loader2 } from 'lucide-react'

import { api, type AttachmentOut, type AttachmentSourceType, getToken } from '../lib/api'
import { filesFromClipboard, usePasteFiles } from '../lib/usePasteFiles'

const ALLOWED_MIME = new Set([
  'image/png', 'image/jpeg', 'image/webp', 'application/pdf', 'text/csv',
])
const MAX_BYTES = 10 * 1024 * 1024

type AttachmentKind = 'image' | 'pdf' | 'csv' | 'other'

interface UploadGhost {
  id: string                // local UUID
  name: string
  size: number
  kind: AttachmentKind
  /** Object URL for image previews so the user sees what they just pasted. */
  preview_url?: string
}

const DUPLICATE_PASTE_WINDOW_MS = 1500

function ghostId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  return `g-${Math.random().toString(36).slice(2)}-${Date.now()}`
}

function kindForMime(mime: string): AttachmentKind {
  if (mime.startsWith('image/')) return 'image'
  if (mime === 'application/pdf') return 'pdf'
  if (mime === 'text/csv') return 'csv'
  return 'other'
}

interface Props {
  notes: string
  onNotesSave: (notes: string) => Promise<void>
  sourceType: AttachmentSourceType
  sourceId: string
  attachments: AttachmentOut[]
  onAttachmentsChanged: () => void | Promise<void>
  /** Default "Notas & documentos · N arquivos" — caller can override. */
  label?: string
}

function fmtSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

function fmtDate(iso: string): string {
  try {
    const d = new Date(iso)
    return d.toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' })
  } catch {
    return iso
  }
}

function KindIcon({ kind, className = 'w-4 h-4' }: { kind: AttachmentKind; className?: string }) {
  switch (kind) {
    case 'image': return <ImageIcon className={className} />
    case 'pdf':   return <FileText className={className} />
    case 'csv':   return <FileSpreadsheet className={className} />
    default:      return <FileIcon className={className} />
  }
}

export default function NotesAttachmentsCard({
  notes, onNotesSave,
  sourceType, sourceId,
  attachments, onAttachmentsChanged,
  label,
}: Props) {
  const [localNotes, setLocalNotes] = useState(notes)
  const [savingNotes, setSavingNotes] = useState(false)
  const [dragActive, setDragActive] = useState(false)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const [inFlight, setInFlight] = useState<UploadGhost[]>([])
  const [pasteFlash, setPasteFlash] = useState(false)
  /** IDs of attachments currently being deleted — shown with a spinner
   *  + reduced opacity so the user gets immediate visual feedback. */
  const [deletingIds, setDeletingIds] = useState<Set<string>>(new Set())
  const fileInputRef = useRef<HTMLInputElement>(null)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const lastSavedRef = useRef(notes)
  const rootRef = useRef<HTMLDivElement>(null)
  /** Last few content-hashes of uploaded files so a repeated ⌘V on the
   *  same clipboard contents is ignored within a short window. The user
   *  was double-uploading because the first paste seemed unresponsive —
   *  this guards the gap until the spinner row shows up. */
  const recentHashesRef = useRef<{ hash: string; at: number }[]>([])

  // Sync down when the parent reloads with fresh notes.
  useEffect(() => {
    setLocalNotes(notes)
    lastSavedRef.current = notes
  }, [notes])

  function scheduleNoteSave(next: string) {
    setLocalNotes(next)
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(async () => {
      if (next === lastSavedRef.current) return
      setSavingNotes(true)
      try {
        await onNotesSave(next)
        lastSavedRef.current = next
      } catch {
        // Silent — the parent should surface its own error. Keep the
        // typed value so the user doesn't lose it.
      } finally {
        setSavingNotes(false)
      }
    }, 800)
  }

  // Flush pending notes save when the component unmounts.
  useEffect(() => () => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
  }, [])

  /** Cheap content hash so two identical pastes in a row are caught.
   *  Clipboard pastes from the OS stamp `lastModified = now()` every
   *  time, so we deliberately exclude it — same screenshot pasted
   *  twice has the same name + size + type. */
  function fileFingerprint(f: File): string {
    return `${f.name}:${f.size}:${f.type}`
  }

  async function uploadFiles(rawFiles: FileList | File[]) {
    setUploadError(null)
    const rejected: string[] = []
    const accepted: File[] = []
    const now = Date.now()
    // Prune the dedupe window first so old entries don't linger.
    recentHashesRef.current = recentHashesRef.current.filter(
      h => now - h.at < DUPLICATE_PASTE_WINDOW_MS,
    )

    for (const f of Array.from(rawFiles)) {
      if (!ALLOWED_MIME.has(f.type)) {
        rejected.push(`${f.name}: tipo "${f.type || 'desconhecido'}" não permitido`)
        continue
      }
      if (f.size > MAX_BYTES) {
        rejected.push(`${f.name}: ${fmtSize(f.size)} excede 10 MB`)
        continue
      }
      const fp = fileFingerprint(f)
      if (recentHashesRef.current.some(h => h.hash === fp)) {
        // Silent skip — the user double-tapped ⌘V; we already have it.
        continue
      }
      recentHashesRef.current.push({ hash: fp, at: now })
      accepted.push(f)
    }

    if (accepted.length === 0) {
      setUploadError(rejected.length ? rejected.join(' · ') : null)
      return
    }

    // Build ghost rows so the user sees feedback the instant they paste.
    const ghosts: UploadGhost[] = accepted.map(f => {
      const kind = kindForMime(f.type)
      return {
        id: ghostId(),
        name: f.name || `colado-${kind}`,
        size: f.size,
        kind,
        preview_url: kind === 'image' ? URL.createObjectURL(f) : undefined,
      }
    })
    setInFlight(prev => [...prev, ...ghosts])

    // Flash the dropzone briefly so the user gets a "received" beat.
    setPasteFlash(true)
    setTimeout(() => setPasteFlash(false), 600)

    // Upload SEQUENTIALLY — the backend uses SQLite which only allows a
    // single writer at a time. Two parallel POSTs were occasionally
    // returning 500 ("database is locked"). Serial is fast enough for
    // human-paced pasting (the user's ⌘V cadence dominates anyway).
    for (let idx = 0; idx < accepted.length; idx++) {
      const f = accepted[idx]
      const g = ghosts[idx]
      try {
        await api.uploadAttachment(sourceType, sourceId, f)
      } catch (err) {
        rejected.push(`${f.name}: ${err instanceof Error ? err.message : 'falhou'}`)
      } finally {
        setInFlight(prev => prev.filter(p => p.id !== g.id))
        if (g.preview_url) URL.revokeObjectURL(g.preview_url)
      }
    }

    await onAttachmentsChanged()
    setUploadError(rejected.length ? rejected.join(' · ') : null)
  }

  function handlePaste(e: React.ClipboardEvent<HTMLTextAreaElement>) {
    const files = filesFromClipboard(e.clipboardData)
    if (files.length === 0) return
    e.preventDefault()
    void uploadFiles(files)
  }

  // CMD-V só responde se o cursor está sobre o card. Padrão system-wide
  // via usePasteFiles. O handlePaste local no textarea continua sendo a
  // primeira linha de defesa (preventDefault interno impede o hook).
  usePasteFiles(rootRef, files => void uploadFiles(files))

  function handleDrop(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault(); e.stopPropagation()
    setDragActive(false)
    if (e.dataTransfer?.files?.length) void uploadFiles(e.dataTransfer.files)
  }
  function handleDragOver(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault(); e.stopPropagation()
    setDragActive(true)
  }
  function handleDragLeave(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault(); e.stopPropagation()
    setDragActive(false)
  }
  function handleFileInput(e: React.ChangeEvent<HTMLInputElement>) {
    if (e.target.files?.length) void uploadFiles(e.target.files)
    e.target.value = ''
  }

  async function handleDelete(id: string) {
    setDeletingIds(prev => {
      const next = new Set(prev); next.add(id); return next
    })
    try {
      await api.deleteAttachment(id)
      await onAttachmentsChanged()
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : 'Erro ao remover anexo')
    } finally {
      setDeletingIds(prev => {
        const next = new Set(prev); next.delete(id); return next
      })
    }
  }

  function handleDownload(att: AttachmentOut) {
    // Server requires Bearer token — use fetch+blob trick to attach the
    // Authorization header (a plain <a href> can't send one).
    const token = getToken()
    fetch(`/api/attachments/${att.id}/download`, {
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    })
      .then(r => r.ok ? r.blob() : Promise.reject(new Error(`HTTP ${r.status}`)))
      .then(blob => {
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = att.filename
        document.body.appendChild(a)
        a.click()
        a.remove()
        setTimeout(() => URL.revokeObjectURL(url), 1000)
      })
      .catch(e => setUploadError(e instanceof Error ? e.message : 'Erro no download'))
  }

  const fileCount = attachments.length
  const sectionTitle = label
    ?? `Notas & documentos${fileCount > 0 ? ` · ${fileCount} ${fileCount === 1 ? 'arquivo' : 'arquivos'}` : ''}`

  return (
    <div
      ref={rootRef}
      className="rounded-xl bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 p-3 space-y-3"
      data-testid="notes-attachments-card"
    >
      <div className="flex items-center justify-between">
        <div className="text-[10px] uppercase tracking-wider text-gray-500 dark:text-gray-400 font-semibold">
          {sectionTitle}
        </div>
        {savingNotes && <span className="text-[10px] text-gray-400">salvando…</span>}
      </div>

      <textarea
        value={localNotes}
        onChange={e => scheduleNoteSave(e.target.value)}
        onPaste={handlePaste}
        placeholder="Adicionar nota… ex: tese do investimento, motivo da compra, link pra notícia, observações pra IR…"
        rows={Math.max(3, localNotes.split('\n').length + 1)}
        className="w-full text-[13px] p-3 rounded-lg bg-gray-50 dark:bg-gray-800/40 border border-gray-200 dark:border-gray-800 placeholder:text-gray-500 text-gray-900 dark:text-white focus:outline-none focus:border-indigo-500 transition-colors resize-y leading-relaxed"
      />

      {(attachments.length > 0 || inFlight.length > 0) && (
        <div>
          <div className="text-[10px] uppercase tracking-wider text-gray-500 font-medium mb-1 flex items-center gap-1.5">
            Anexos
            {inFlight.length > 0 && (
              <span
                className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-indigo-500/15 text-indigo-400 text-[10px] font-semibold normal-case tracking-normal"
                data-testid="upload-status-banner"
              >
                <Loader2 className="w-3 h-3 animate-spin" />
                Enviando {inFlight.length} {inFlight.length === 1 ? 'arquivo' : 'arquivos'}…
              </span>
            )}
          </div>
          <div className="space-y-0.5" data-testid="attachments-list">
            {inFlight.map(g => (
              <UploadingRow key={g.id} ghost={g} />
            ))}
            {attachments.map(att => (
              <AttachmentRow
                key={att.id}
                attachment={att}
                deleting={deletingIds.has(att.id)}
                onDownload={() => handleDownload(att)}
                onDelete={() => handleDelete(att.id)}
              />
            ))}
          </div>
        </div>
      )}

      {/* Drop zone — paste / drag / click. Mirrors prototype PasteDropZone
          (index.html:4155). Flashes briefly when ⌘V lands so the user
          knows the paste was received even before the upload finishes. */}
      <div
        onDrop={handleDrop}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onClick={() => fileInputRef.current?.click()}
        className={`p-5 rounded-lg border-2 border-dashed text-center transition-colors cursor-pointer ${
          dragActive || pasteFlash
            ? 'border-indigo-500 bg-indigo-500/15'
            : 'border-gray-300 dark:border-gray-700 hover:border-indigo-500/50'
        }`}
        data-testid="notes-attachments-dropzone"
      >
        {pasteFlash ? (
          <>
            <Loader2 className="w-5 h-5 mx-auto text-indigo-400 animate-spin" />
            <p className="text-[12px] text-indigo-400 font-medium mt-2">Recebido — enviando…</p>
          </>
        ) : (
          <>
            <Paperclip className="w-5 h-5 mx-auto text-gray-500" />
            <p className="text-[12px] text-gray-500 mt-2">
              Cole uma imagem com <kbd className="px-1.5 py-0.5 mx-0.5 rounded bg-gray-200 dark:bg-gray-800 text-[10px] font-mono">⌘V</kbd>,
              arraste um PDF ou{' '}
              <span className="text-indigo-400 hover:text-indigo-300 underline-offset-2 hover:underline">
                selecione um arquivo
              </span>
            </p>
            <p className="text-[10px] text-gray-400 dark:text-gray-600 mt-1">
              PNG · JPG · WEBP · PDF · CSV até 10 MB
            </p>
          </>
        )}
      </div>
      <input
        ref={fileInputRef}
        type="file"
        accept="image/png,image/jpeg,image/webp,application/pdf,text/csv"
        multiple
        onChange={handleFileInput}
        className="hidden"
        data-testid="notes-attachments-input"
      />

      {uploadError && (
        <p className="text-[11px] text-red-500 dark:text-red-400" data-testid="upload-error">
          {uploadError}
        </p>
      )}
    </div>
  )
}


/** Pending-upload row shown above the persisted list. The mini preview on
 *  the left uses the same object URL we generated when the user pasted, so
 *  it shows up the instant ⌘V is pressed — no wait for the server. */
function UploadingRow({ ghost }: { ghost: UploadGhost }) {
  const isImg = ghost.kind === 'image'
  return (
    <div
      className="group flex items-center gap-3 px-2 py-2 -mx-2 rounded-lg bg-indigo-500/5 border border-indigo-500/20"
      data-testid="upload-ghost-row"
    >
      <div className={`w-9 h-9 rounded-md flex items-center justify-center shrink-0 overflow-hidden ${
        isImg ? 'bg-blue-500/15 text-blue-400' : 'bg-red-500/15 text-red-400'
      }`}>
        {ghost.preview_url ? (
          <img src={ghost.preview_url} alt="" className="w-full h-full object-cover" />
        ) : (
          <KindIcon kind={ghost.kind} />
        )}
      </div>
      <div className="flex-1 min-w-0">
        <div className="text-[12px] font-medium truncate text-gray-900 dark:text-white">{ghost.name}</div>
        <div className="text-[11px] text-indigo-400 tnum flex items-center gap-1.5">
          <Loader2 className="w-3 h-3 animate-spin" />
          enviando · {fmtSize(ghost.size)}
        </div>
      </div>
    </div>
  )
}

/** Fetch an attachment's blob with auth and return an object URL. The
 *  browser caches the response (Spec 19's download endpoint doesn't set a
 *  no-store header), and we cache the URL across re-renders so the same
 *  row doesn't refetch on every state update.
 *
 *  V1 trade-off: this downloads the full image just to render a 36×36
 *  thumb. Fine for the typical "≤10 anexos × ≤1 MB" case; Spec 40 covers
 *  a server-side resize when listings grow. */
function useAttachmentImage(id: string, enabled: boolean): string | null {
  const [url, setUrl] = useState<string | null>(null)
  useEffect(() => {
    if (!enabled) return
    let cancelled = false
    let objectUrl: string | null = null
    const token = getToken()
    fetch(`/api/attachments/${id}/download`, {
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    })
      .then(r => r.ok ? r.blob() : Promise.reject(new Error(`HTTP ${r.status}`)))
      .then(blob => {
        if (cancelled) return
        objectUrl = URL.createObjectURL(blob)
        setUrl(objectUrl)
      })
      .catch(() => { /* fall back to icon */ })
    return () => {
      cancelled = true
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [id, enabled])
  return url
}

function AttachmentRow({
  attachment, onDownload, onDelete, deleting,
}: {
  attachment: AttachmentOut
  onDownload: () => void
  onDelete: () => void
  deleting?: boolean
}) {
  const kind = attachment.kind as AttachmentKind
  const isImg = kind === 'image'
  const imageUrl = useAttachmentImage(attachment.id, isImg)
  return (
    <div
      className={`group flex items-center gap-3 px-2 py-2 -mx-2 rounded-lg transition-colors ${
        deleting
          ? 'opacity-50 bg-red-500/5 pointer-events-none'
          : 'hover:bg-gray-100 dark:hover:bg-gray-800/50'
      }`}
      data-testid="attachment-row"
    >
      <div className={`w-9 h-9 rounded-md flex items-center justify-center shrink-0 overflow-hidden ${
        isImg ? 'bg-blue-500/15 text-blue-400' : 'bg-red-500/15 text-red-400'
      }`}>
        {isImg && imageUrl ? (
          <img
            src={imageUrl}
            alt={attachment.filename}
            className="w-full h-full object-cover"
            data-testid="attachment-thumb"
          />
        ) : (
          <KindIcon kind={kind} />
        )}
      </div>
      <div className="flex-1 min-w-0">
        <div className="text-[12px] font-medium truncate text-gray-900 dark:text-white">{attachment.filename}</div>
        <div className="text-[11px] text-gray-500 tnum flex items-center gap-1.5">
          {deleting ? (
            <>
              <Loader2 className="w-3 h-3 animate-spin text-red-400" />
              <span className="text-red-400">removendo…</span>
            </>
          ) : (
            <>{fmtSize(attachment.size_bytes)} · {fmtDate(attachment.uploaded_at)}</>
          )}
        </div>
      </div>
      {!deleting && (
        <div className="opacity-0 group-hover:opacity-100 transition-opacity flex items-center gap-1">
          <button
            type="button"
            onClick={onDownload}
            title="Baixar"
            className="w-7 h-7 inline-flex items-center justify-center rounded-md text-gray-500 hover:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-800"
          >
            <Download className="w-3.5 h-3.5" />
          </button>
          <button
            type="button"
            onClick={onDelete}
            title="Remover"
            className="w-7 h-7 inline-flex items-center justify-center rounded-md text-gray-500 hover:text-red-400 hover:bg-red-500/10"
          >
            <Trash2 className="w-3.5 h-3.5" />
          </button>
        </div>
      )}
    </div>
  )
}
