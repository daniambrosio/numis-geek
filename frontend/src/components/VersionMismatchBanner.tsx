/* Spec 54 — banner que avisa quando o backend reporta um sha
 * diferente do que tá baked no frontend (deploy novo + browser
 * cacheado). Faz polling discreto (a cada 5 min) + uma chamada inicial
 * 2s após mount.
 *
 * UX: banner colapsável (X dismissa até a próxima poll detectar de novo).
 * Botão "Atualizar" força hard reload.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { RefreshCw, X } from 'lucide-react'

import { api } from '../lib/api'

const POLL_MS = 5 * 60 * 1000  // 5 min
const INITIAL_DELAY_MS = 2000

export default function VersionMismatchBanner() {
  const [serverInfo, setServerInfo] = useState<{ version: string; sha: string } | null>(null)
  const [dismissed, setDismissed] = useState<string | null>(null)
  const lastSeenSha = useRef<string | null>(null)

  const check = useCallback(async () => {
    try {
      const info = await api.version()
      lastSeenSha.current = info.sha
      if (info.sha !== __APP_SHA__) {
        setServerInfo({ version: info.version, sha: info.sha })
      } else {
        setServerInfo(null)
        setDismissed(null)
      }
    } catch {
      // Backend offline / 404 — não mostra nada (não é mismatch).
    }
  }, [])

  useEffect(() => {
    const t0 = setTimeout(check, INITIAL_DELAY_MS)
    const t1 = setInterval(check, POLL_MS)
    return () => { clearTimeout(t0); clearInterval(t1) }
  }, [check])

  if (!serverInfo) return null
  if (dismissed === serverInfo.sha) return null

  function handleReload() {
    // Hard reload: bypassa cache do browser pra forçar bundle novo.
    window.location.reload()
  }

  return (
    <div
      className="px-4 py-2 bg-amber-500/10 border-b border-amber-500/20 flex items-center gap-3 text-[12px]"
      data-testid="version-mismatch-banner"
      role="alert"
    >
      <span className="text-amber-700 dark:text-amber-300">
        Nova versão disponível: <strong className="tnum">v{serverInfo.version}</strong>
        {' · '}<span className="tnum text-amber-700/80 dark:text-amber-300/80">{serverInfo.sha}</span>
      </span>
      <button
        onClick={handleReload}
        className="h-7 px-2.5 inline-flex items-center gap-1 rounded-md bg-amber-500 hover:bg-amber-400 text-white text-[11px] font-medium"
        data-testid="version-mismatch-reload"
      >
        <RefreshCw className="w-3 h-3" /> Atualizar
      </button>
      <div className="flex-1" />
      <button
        onClick={() => setDismissed(serverInfo.sha)}
        className="w-6 h-6 inline-flex items-center justify-center rounded text-amber-700/70 dark:text-amber-300/70 hover:bg-amber-500/15"
        title="Lembrar depois"
        data-testid="version-mismatch-dismiss"
      >
        <X className="w-3.5 h-3.5" />
      </button>
    </div>
  )
}
