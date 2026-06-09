/* Hook compartilhado pra paste com escopo de hover.
 *
 * Por que existe: quando vários componentes registram um listener
 * global de `paste` ao mesmo tempo (vários BulkAttachmentManagers, ou
 * MovementComposer + NotesAttachmentsField), todos disparam o mesmo
 * CMD-V e o arquivo entra em vários slots em paralelo. Aqui o handler
 * só responde se o cursor estiver sobre o `zoneRef`.
 *
 * Uso:
 *
 *   const zoneRef = useRef<HTMLDivElement>(null)
 *   usePasteFiles(zoneRef, files => uploadAll(files), { enabled: !busy })
 *   return <div ref={zoneRef}>…</div>
 */
import { useEffect, type RefObject } from 'react'

type PasteFilesOptions = {
  /** Quando false, o handler não dispara — útil pra pausar durante upload. */
  enabled?: boolean
  /** Por default, dispara só com cursor dentro do zoneRef. Quando true,
   *  também aceita paste quando o evento veio de DENTRO do zone
   *  (ex: cole no textarea filho). Pra textareas com onPaste local,
   *  deixe false. */
  acceptEventTargetInZone?: boolean
}

export function usePasteFiles(
  zoneRef: RefObject<HTMLElement | null>,
  onFiles: (files: File[]) => void,
  opts: PasteFilesOptions = {},
): void {
  const { enabled = true, acceptEventTargetInZone = false } = opts
  useEffect(() => {
    if (!enabled) return
    let lastX = -1
    let lastY = -1
    function onMove(e: MouseEvent) {
      lastX = e.clientX
      lastY = e.clientY
    }
    function onPaste(e: ClipboardEvent) {
      const zone = zoneRef.current
      if (!zone) return
      // Gate por hover: só o slot sob o cursor recebe.
      let inZone = false
      if (lastX >= 0 && lastY >= 0) {
        const el = document.elementFromPoint(lastX, lastY)
        if (el && zone.contains(el)) inZone = true
      }
      if (!inZone && acceptEventTargetInZone) {
        const target = e.target as Element | null
        if (target && zone.contains(target)) inZone = true
      }
      if (!inZone) return

      const files = filesFromClipboard(e.clipboardData)
      if (files.length === 0) return
      e.preventDefault()
      onFiles(files)
    }
    document.addEventListener('mousemove', onMove)
    document.addEventListener('paste', onPaste)
    return () => {
      document.removeEventListener('mousemove', onMove)
      document.removeEventListener('paste', onPaste)
    }
  }, [zoneRef, onFiles, enabled, acceptEventTargetInZone])
}

/** Extrai arquivos do clipboard com dedup por (name, size). Prioriza
 *  cb.files se presente — Chrome populava tanto cb.files quanto cb.items
 *  com lastModified microssegundos diferentes, e o dedup por
 *  (name, size, lastModified) deixava passar duplicata. */
export function filesFromClipboard(cb: DataTransfer | null): File[] {
  if (!cb) return []
  const out: File[] = []
  const seen = new Set<string>()
  const push = (f: File) => {
    const key = `${f.name}:${f.size}`
    if (!seen.has(key)) { seen.add(key); out.push(f) }
  }
  if (cb.files && cb.files.length) {
    for (const f of Array.from(cb.files)) push(f)
    return out
  }
  if (cb.items && cb.items.length) {
    for (const it of Array.from(cb.items)) {
      if (it.kind === 'file') {
        const f = it.getAsFile()
        if (f) push(f)
      }
    }
  }
  return out
}
