import { useMemo, useState } from 'react'
import { ExternalLink, X } from 'lucide-react'
import { Link } from 'react-router-dom'

import type { AuditLogOut } from '../lib/api'
import { describeAudit, toneClasses } from '../lib/auditCatalog'
import { useEscapeKey } from '../lib/useEscapeKey'

interface Props {
  log: AuditLogOut | null
  onClose: () => void
}

function prettyJson(raw: string | null): string {
  if (!raw) return ''
  try {
    return JSON.stringify(JSON.parse(raw), null, 2)
  } catch {
    return raw
  }
}

export default function AuditDetailDrawer({ log, onClose }: Props) {
  useEscapeKey(() => { if (log) onClose() })

  const [showRaw, setShowRaw] = useState(false)

  const desc = useMemo(() => (log ? describeAudit(log) : null), [log])
  const detailsJson = useMemo(() => prettyJson(log?.details ?? null), [log])

  if (!log || !desc) return null

  const dt = new Date(log.created_at)

  return (
    <div className="fixed inset-0 z-[70] flex">
      <button
        type="button"
        aria-label="Fechar"
        onClick={onClose}
        className="flex-1 bg-black/40 backdrop-blur-sm"
      />
      <aside
        className="w-full max-w-md h-full bg-white dark:bg-gray-950 border-l border-gray-200 dark:border-gray-800 shadow-2xl overflow-y-auto flex flex-col"
        role="dialog"
        aria-modal="true"
      >
        {/* Header */}
        <div className="flex items-start justify-between gap-3 p-5 border-b border-gray-100 dark:border-gray-800">
          <div className="space-y-2 min-w-0">
            <span className={`inline-flex px-2 py-0.5 rounded-full text-xs font-medium ${toneClasses(desc.actionTone)}`}>
              {desc.actionLabel}
            </span>
            <h2 className="text-base font-semibold text-gray-900 dark:text-gray-100 truncate">
              {desc.resourceLabel}
            </h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Fechar"
            className="p-1 rounded-lg text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800"
          >
            <X size={18} />
          </button>
        </div>

        {/* Body */}
        <div className="p-5 space-y-5 flex-1">
          <section>
            <div className="text-[11px] uppercase tracking-wide text-gray-400 dark:text-gray-500 mb-2">
              Resumo
            </div>
            <p className="text-sm text-gray-700 dark:text-gray-200 leading-relaxed">
              {desc.summary}
            </p>
          </section>

          <section className="space-y-1">
            <div className="text-[11px] uppercase tracking-wide text-gray-400 dark:text-gray-500 mb-2">
              Quem & quando
            </div>
            <dl className="text-sm space-y-1.5">
              <div className="flex justify-between gap-3">
                <dt className="text-gray-500 dark:text-gray-400">Usuário</dt>
                <dd className="text-gray-700 dark:text-gray-200 text-right truncate">{log.user_email}</dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt className="text-gray-500 dark:text-gray-400">Quando</dt>
                <dd className="text-gray-700 dark:text-gray-200 text-right">
                  {dt.toLocaleString('pt-BR')}
                </dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt className="text-gray-500 dark:text-gray-400">Ação</dt>
                <dd className="text-gray-700 dark:text-gray-200 text-right font-mono text-xs">{log.action}</dd>
              </div>
              {log.resource_type && (
                <div className="flex justify-between gap-3">
                  <dt className="text-gray-500 dark:text-gray-400">Tipo</dt>
                  <dd className="text-gray-700 dark:text-gray-200 text-right font-mono text-xs">{log.resource_type}</dd>
                </div>
              )}
              {log.resource_id && (
                <div className="flex justify-between gap-3">
                  <dt className="text-gray-500 dark:text-gray-400">ID</dt>
                  <dd className="text-gray-700 dark:text-gray-200 text-right font-mono text-xs break-all">{log.resource_id}</dd>
                </div>
              )}
            </dl>
          </section>

          {detailsJson && (
            <section>
              <button
                type="button"
                onClick={() => setShowRaw(v => !v)}
                className="text-[11px] uppercase tracking-wide text-gray-400 dark:text-gray-500 mb-2 hover:text-gray-600 dark:hover:text-gray-300 transition-colors"
              >
                {showRaw ? '▾' : '▸'} Detalhes (JSON)
              </button>
              {showRaw && (
                <pre className="mt-2 text-[11px] font-mono leading-snug bg-gray-50 dark:bg-gray-900 border border-gray-100 dark:border-gray-800 rounded-lg p-3 overflow-x-auto whitespace-pre text-gray-700 dark:text-gray-300">
                  {detailsJson}
                </pre>
              )}
            </section>
          )}
        </div>

        {/* Footer */}
        {desc.link && (
          <div className="p-5 border-t border-gray-100 dark:border-gray-800">
            <Link
              to={desc.link.to}
              onClick={onClose}
              className="inline-flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium bg-indigo-500 text-white hover:bg-indigo-600 transition-colors"
            >
              <ExternalLink size={14} />
              {desc.link.label}
            </Link>
          </div>
        )}
      </aside>
    </div>
  )
}
