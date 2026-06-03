import { useEffect, useRef, useState } from 'react'
import { Paperclip, Trash2, FileText, Image as ImageIcon, FileSpreadsheet, File as FileIcon } from 'lucide-react'

// Mirrors the storage whitelist on the backend (services/attachment_storage.py).
// Keep these in sync — sending a MIME outside this set returns 415.
const ALLOWED_MIME: Record<string, AttachmentKind> = {
  'image/png': 'image',
  'image/jpeg': 'image',
  'image/webp': 'image',
  'application/pdf': 'pdf',
  'text/csv': 'csv',
}
const MAX_BYTES = 10 * 1024 * 1024

export type AttachmentKind = 'image' | 'pdf' | 'csv' | 'other'

export interface AttachmentDraft {
  /** Local UUID until the parent persists the row. */
  id: string
  file: File
  name: string
  size: number
  mime_type: string
  kind: AttachmentKind
  /** Object URL for image previews — caller must revoke on unmount. */
  preview_url?: string
}

export interface PersistedAttachment {
  id: string
  filename: string
  size_bytes: number
  mime_type: string
  kind: AttachmentKind
}

interface Props {
  notes: string
  onNotesChange: (s: string) => void
  files: AttachmentDraft[]
  onFilesChange: (xs: AttachmentDraft[]) => void
  /** Already-persisted Attachment rows shown above the drafts. */
  persisted?: PersistedAttachment[]
  /** Called when the user clicks the trash icon on a persisted attachment. */
  onRemovePersisted?: (id: string) => void
  placeholder?: string
  notesRows?: number
}

function kindFor(mime: string): AttachmentKind {
  return ALLOWED_MIME[mime] ?? 'other'
}

function makeId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  return `local-${Math.random().toString(36).slice(2)}-${Date.now()}`
}

function fmtSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

function KindIcon({ kind, className = 'w-3.5 h-3.5' }: { kind: AttachmentKind; className?: string }) {
  switch (kind) {
    case 'image': return <ImageIcon className={className} />
    case 'pdf':   return <FileText className={className} />
    case 'csv':   return <FileSpreadsheet className={className} />
    default:      return <FileIcon className={className} />
  }
}

export default function NotesAttachmentsField({
  notes, onNotesChange,
  files, onFilesChange,
  persisted, onRemovePersisted,
  placeholder = 'ex: tese, motivo da compra, link pra notícia…',
  notesRows = 2,
}: Props) {
  const [dragActive, setDragActive] = useState(false)
  const [validationError, setValidationError] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const rootRef = useRef<HTMLDivElement>(null)

  // Clean up object URLs when the component unmounts.
  useEffect(() => {
    return () => {
      for (const f of files) if (f.preview_url) URL.revokeObjectURL(f.preview_url)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  /** Extract Files from a ClipboardEvent — see NotesAttachmentsCard for
   *  the rationale (items vs files across browsers). */
  function filesFromClipboard(cb: DataTransfer | null): File[] {
    if (!cb) return []
    const out: File[] = []
    const seen = new Set<string>()
    if (cb.files && cb.files.length) {
      for (const f of Array.from(cb.files)) {
        const key = `${f.name}:${f.size}:${f.lastModified}`
        if (!seen.has(key)) { seen.add(key); out.push(f) }
      }
    }
    if (cb.items && cb.items.length) {
      for (const it of Array.from(cb.items)) {
        if (it.kind === 'file') {
          const f = it.getAsFile()
          if (f) {
            const key = `${f.name}:${f.size}:${f.lastModified}`
            if (!seen.has(key)) { seen.add(key); out.push(f) }
          }
        }
      }
    }
    return out
  }

  function validateAndAdd(rawFiles: FileList | File[]): void {
    const accepted: AttachmentDraft[] = []
    const rejected: string[] = []
    for (const file of Array.from(rawFiles)) {
      if (!ALLOWED_MIME[file.type]) {
        rejected.push(`${file.name}: tipo "${file.type || 'desconhecido'}" não permitido`)
        continue
      }
      if (file.size > MAX_BYTES) {
        rejected.push(`${file.name}: ${fmtSize(file.size)} excede o limite de 10 MB`)
        continue
      }
      const kind = kindFor(file.type)
      const draft: AttachmentDraft = {
        id: makeId(),
        file,
        name: file.name,
        size: file.size,
        mime_type: file.type,
        kind,
        preview_url: kind === 'image' ? URL.createObjectURL(file) : undefined,
      }
      accepted.push(draft)
    }
    if (accepted.length) onFilesChange([...files, ...accepted])
    setValidationError(rejected.length ? rejected.join(' · ') : null)
  }

  function handlePaste(e: React.ClipboardEvent<HTMLTextAreaElement>) {
    const files = filesFromClipboard(e.clipboardData)
    if (files.length === 0) return
    e.preventDefault()
    validateAndAdd(files)
  }

  // Catch ⌘V even when the textarea isn't focused. Skip when the paste
  // landed inside our own textarea (handlePaste already consumed it) or
  // inside another editable element elsewhere on the page.
  useEffect(() => {
    function onWindowPaste(e: ClipboardEvent) {
      const target = e.target as Element | null
      if (target && rootRef.current?.contains(target)) {
        return
      }
      if (
        target &&
        (target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement || (target as HTMLElement).isContentEditable)
      ) {
        return
      }
      const files = filesFromClipboard(e.clipboardData)
      if (files.length === 0) return
      e.preventDefault()
      validateAndAdd(files)
    }
    window.addEventListener('paste', onWindowPaste)
    return () => window.removeEventListener('paste', onWindowPaste)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function handleDrop(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault()
    e.stopPropagation()
    setDragActive(false)
    if (e.dataTransfer?.files?.length) validateAndAdd(e.dataTransfer.files)
  }

  function handleDragOver(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault()
    e.stopPropagation()
    setDragActive(true)
  }

  function handleDragLeave(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault()
    e.stopPropagation()
    setDragActive(false)
  }

  function handleFileInput(e: React.ChangeEvent<HTMLInputElement>) {
    if (e.target.files?.length) validateAndAdd(e.target.files)
    e.target.value = ''
  }

  function removeDraft(id: string) {
    const target = files.find(f => f.id === id)
    if (target?.preview_url) URL.revokeObjectURL(target.preview_url)
    onFilesChange(files.filter(f => f.id !== id))
  }

  const totalCount = (persisted?.length ?? 0) + files.length

  return (
    <div ref={rootRef} className="space-y-3" data-testid="notes-attachments-field">
      {/* Label — matches prototype index.html:4208 ("Notas & anexos") */}
      <div>
        <div className="flex items-baseline justify-between mb-1.5">
          <label className="block text-[10px] uppercase tracking-wider font-semibold text-gray-500 dark:text-gray-400">
            Notas & anexos
          </label>
          <span className="text-[10px] text-gray-400 dark:text-gray-600">
            · opcional · ⌘V cola imagem · arraste PDF
          </span>
        </div>
        <textarea
          value={notes}
          onChange={e => onNotesChange(e.target.value)}
          onPaste={handlePaste}
          rows={notesRows}
          placeholder={placeholder}
          className="w-full px-3 py-2 text-[13px] rounded-md bg-gray-50 dark:bg-gray-800/50 border border-gray-200 dark:border-gray-800 text-gray-900 dark:text-white placeholder:text-gray-400 dark:placeholder:text-gray-600 focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 resize-none"
        />
      </div>

      {/* Attachments list — matches prototype index.html:4217-4239. Each
          row: kind icon + filename + size + trash button. Drafts get an
          indigo "novo" pill; persisted files get a neutral background. */}
      {totalCount > 0 && (
        <div className="space-y-0.5" data-testid="notes-attachments-list">
          <div className="text-[10px] uppercase tracking-wider text-gray-500 font-medium px-0.5">
            Anexos · {totalCount}
          </div>
          {persisted?.map(att => (
            <AttachmentRow
              key={att.id}
              kind={att.kind}
              name={att.filename}
              sizeLabel={fmtSize(att.size_bytes)}
              accentBg={att.kind === 'image' ? 'bg-blue-500/15 text-blue-400' : 'bg-red-500/15 text-red-400'}
              testid="notes-attachments-persisted"
              onRemove={onRemovePersisted ? () => onRemovePersisted(att.id) : undefined}
            />
          ))}
          {files.map(draft => (
            <AttachmentRow
              key={draft.id}
              kind={draft.kind}
              name={draft.name}
              sizeLabel={fmtSize(draft.size)}
              accentBg={draft.kind === 'image' ? 'bg-blue-500/15 text-blue-400' : 'bg-red-500/15 text-red-400'}
              previewUrl={draft.preview_url}
              testid="notes-attachments-draft"
              badge="novo"
              onRemove={() => removeDraft(draft.id)}
            />
          ))}
        </div>
      )}

      {/* Drop zone — matches prototype index.html:4240-4251. Big dashed
          border, paperclip icon centered, "Cole / arraste / selecione". */}
      <div
        onDrop={handleDrop}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onClick={() => fileInputRef.current?.click()}
        className={`p-3 rounded-lg border-2 border-dashed text-center transition-colors cursor-pointer ${
          dragActive
            ? 'border-indigo-500 bg-indigo-50/40 dark:bg-indigo-900/10'
            : 'border-gray-300 dark:border-gray-700 hover:border-indigo-500/50'
        }`}
        data-testid="notes-attachments-dropzone"
      >
        <Paperclip className="w-4 h-4 mx-auto text-gray-500" />
        <p className="text-[11px] text-gray-500 mt-1.5">
          Cole com <kbd className="px-1 py-0.5 mx-0.5 rounded bg-gray-200 dark:bg-gray-800 text-[9px] font-mono">⌘V</kbd>,
          arraste ou{' '}
          <span className="text-indigo-400 hover:text-indigo-300 underline-offset-2 hover:underline">
            selecione um arquivo
          </span>
        </p>
        <p className="text-[10px] text-gray-400 dark:text-gray-600 mt-1">
          PNG · JPG · WEBP · PDF · CSV até 10 MB
        </p>
      </div>
      <input
        ref={fileInputRef}
        type="file"
        accept={Object.keys(ALLOWED_MIME).join(',')}
        multiple
        onChange={handleFileInput}
        className="hidden"
        data-testid="notes-attachments-input"
      />

      {validationError && (
        <p className="text-[11px] text-red-600 dark:text-red-400" data-testid="notes-attachments-error">
          {validationError}
        </p>
      )}
    </div>
  )
}


function AttachmentRow({
  kind, name, sizeLabel, accentBg, previewUrl, testid, badge, onRemove,
}: {
  kind: AttachmentKind
  name: string
  sizeLabel: string
  accentBg: string
  previewUrl?: string
  testid?: string
  badge?: string
  onRemove?: () => void
}) {
  return (
    <div
      className="group flex items-center gap-3 px-2 py-1.5 rounded-lg border border-gray-200 dark:border-gray-800"
      data-testid={testid}
    >
      {previewUrl ? (
        <img
          src={previewUrl}
          alt={name}
          className="w-10 h-10 rounded-md object-cover shrink-0 border border-gray-200 dark:border-gray-800"
        />
      ) : (
        <div className={`w-7 h-7 rounded-md flex items-center justify-center shrink-0 ${accentBg}`}>
          <KindIcon kind={kind} />
        </div>
      )}
      <div className="flex-1 min-w-0">
        <div className="text-[12px] font-medium truncate text-gray-900 dark:text-white">{name}</div>
        <div className="text-[10px] text-gray-500 tnum">{sizeLabel}</div>
      </div>
      {badge && (
        <span className="text-[9px] uppercase tracking-wider font-semibold text-indigo-500 dark:text-indigo-300 shrink-0">
          {badge}
        </span>
      )}
      {onRemove && (
        <button
          type="button"
          onClick={onRemove}
          title={badge ? 'Descartar' : 'Remover'}
          className="w-6 h-6 inline-flex items-center justify-center rounded-md text-gray-500 hover:text-red-400 hover:bg-red-500/10 shrink-0"
        >
          <Trash2 className="w-3 h-3" />
        </button>
      )}
    </div>
  )
}
