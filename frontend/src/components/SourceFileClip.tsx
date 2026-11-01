/* Spec 71 — clipe na linha da movimentação: abre o extrato/fatura de onde
 * ela veio (rastreabilidade arquivo → transação). */
import { useState } from 'react'
import { Loader2, Paperclip } from 'lucide-react'
import { openAttachmentPreview } from '../lib/openAttachment'

export default function SourceFileClip({ attachmentId, filename, onError }: {
  attachmentId: string | null | undefined
  filename?: string | null
  onError: (message: string) => void
}) {
  const [opening, setOpening] = useState(false)
  if (!attachmentId) return null
  async function open(e: React.MouseEvent) {
    e.stopPropagation()
    setOpening(true)
    try {
      await openAttachmentPreview(attachmentId!)
    } catch (err) {
      onError(err instanceof Error ? err.message : 'Erro ao abrir o arquivo.')
    } finally {
      setOpening(false)
    }
  }
  const label = `Abrir arquivo de origem${filename ? `: ${filename}` : ''}`
  return (
    <button type="button" onClick={open} disabled={opening} title={label} aria-label={label}
      className="inline-flex items-center p-0.5 rounded text-gray-400 hover:text-indigo-500 hover:bg-gray-100 dark:hover:bg-gray-800 disabled:opacity-50">
      {opening ? <Loader2 className="w-3 h-3 animate-spin" /> : <Paperclip className="w-3 h-3" />}
    </button>
  )
}
