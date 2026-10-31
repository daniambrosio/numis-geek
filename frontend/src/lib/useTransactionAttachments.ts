/* Spec 70 — anexos de transação, compartilhado pelas 3 páginas que abrem os
 * composers (Movimentações, conta corrente, cartão). Antes só
 * Transactions.tsx ligava o upload; nas outras o picker aparecia e os
 * arquivos eram descartados em silêncio (audit 2026-10-31).
 */
import { useCallback, useRef, useState } from 'react'
import { api } from './api'
import type { AttachmentDraft, PersistedAttachment } from '../components/NotesAttachmentsField'

/** Upload parcial: `failed` são os rascunhos que precisam de nova tentativa
 * (os que subiram não podem ser reenviados — duplicaria o anexo). */
export class AttachmentUploadError extends Error {
  failed: AttachmentDraft[]
  constructor(message: string, failed: AttachmentDraft[]) {
    super(message)
    this.failed = failed
  }
}

export function useTransactionAttachments() {
  const [persisted, setPersisted] = useState<PersistedAttachment[]>([])
  const editingId = useRef<string | null>(null)

  const load = useCallback(async (txId: string) => {
    const list = await api.listAttachments('transaction', txId).catch(() => [])
    if (editingId.current !== txId) return
    setPersisted(list.map(a => ({ id: a.id, filename: a.filename, size_bytes: a.size_bytes, mime_type: a.mime_type, kind: a.kind })))
  }, [])

  /** Abre o composer: `txId` em edição carrega os anexos gravados; null limpa. */
  const startEditing = useCallback((txId: string | null) => {
    editingId.current = txId
    setPersisted([])
    if (txId) void load(txId)
  }, [load])

  const uploadDrafts = useCallback(async (entityId: string, drafts: AttachmentDraft[]) => {
    const results = await Promise.allSettled(drafts.map(d => api.uploadAttachment('transaction', entityId, d.file)))
    const failed = results.map((r, i) => ({ r, d: drafts[i] })).filter(x => x.r.status === 'rejected')
    if (failed.length) {
      throw new AttachmentUploadError(
        failed.map(x => `${x.d.name}: ${(x.r as PromiseRejectedResult).reason?.message ?? 'erro'}`).join(' · '),
        failed.map(x => x.d),
      )
    }
  }, [])

  const removePersisted = useCallback(async (attachmentId: string) => {
    await api.deleteAttachment(attachmentId)
    if (editingId.current) await load(editingId.current)
  }, [load])

  return { persisted, startEditing, uploadDrafts, removePersisted }
}
