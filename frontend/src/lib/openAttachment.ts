import { getToken } from './api'

/** Abre o arquivo num tab novo (preview nativo do browser pra PDF/imagem).
 * /download exige Bearer — busca como blob e abre o object URL (mesmo
 * padrão do BulkAttachmentManager, spec 40/43). */
export async function openAttachmentPreview(attachmentId: string): Promise<void> {
  const token = getToken()
  const r = await fetch(`/api/attachments/${attachmentId}/download`, {
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
  })
  if (!r.ok) throw new Error(`Não foi possível abrir o arquivo (HTTP ${r.status}).`)
  const blob = await r.blob()
  const url = URL.createObjectURL(blob)
  window.open(url, '_blank')
  setTimeout(() => URL.revokeObjectURL(url), 60_000)
}
