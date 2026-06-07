import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, type AuditLogOut, type AuditPage, type UserOut } from '../../lib/api'
import AppLayout from '../../components/AppLayout'
import AuditDetailDrawer from '../../components/AuditDetailDrawer'
import { Card, PageHeader } from '../../components/ui'
import {
  ACTION_FILTER_GROUPS,
  describeAudit,
  toneClasses,
} from '../../lib/auditCatalog'

export default function AdminAudit() {
  const navigate = useNavigate()
  const [me, setMe] = useState<UserOut | null>(null)
  const [data, setData] = useState<AuditPage | null>(null)
  const [page, setPage] = useState(1)
  const [actionFilter, setActionFilter] = useState('')
  const [loading, setLoading] = useState(true)
  const [selected, setSelected] = useState<AuditLogOut | null>(null)

  useEffect(() => {
    api.me().catch(() => navigate('/login')).then(u => u && setMe(u))
  }, [navigate])

  useEffect(() => {
    if (!me) return
    setLoading(true)
    api.listAudit(page, actionFilter || undefined)
      .then(setData)
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [me, page, actionFilter])

  function handleFilterChange(action: string) {
    setActionFilter(action)
    setPage(1)
  }

  if (!me) return null

  return (
    <AppLayout user={me}>
      <div className="space-y-6">
        <PageHeader
          title="Auditoria"
          count={data?.total ?? null}
          countLabel={`registro${(data?.total ?? 0) === 1 ? '' : 's'}`}
          action={
            <select
              value={actionFilter}
              onChange={e => handleFilterChange(e.target.value)}
              className="h-8 px-2 text-[12px] rounded-lg border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 text-gray-700 dark:text-gray-300 focus:outline-none focus:border-indigo-500"
            >
              <option value="">Todas as ações</option>
              {ACTION_FILTER_GROUPS.map(group => (
                <optgroup key={group.label} label={group.label}>
                  {group.actions.map(a => (
                    <option key={a.value} value={a.value}>{a.label}</option>
                  ))}
                </optgroup>
              ))}
            </select>
          }
        />

        <Card padding="p-0"><div className="overflow-hidden rounded-2xl">
          {loading ? (
            <div className="p-12 text-center text-sm text-gray-400 dark:text-gray-600">Carregando…</div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-200 dark:border-gray-800">
                  {['Data', 'Usuário', 'Ação', 'Recurso', 'Resumo'].map(h => (
                    <th key={h} className="text-left px-4 py-3 text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
                {data?.items.map((log: AuditLogOut) => {
                  const desc = describeAudit(log)
                  return (
                    <tr
                      key={log.id}
                      onClick={() => setSelected(log)}
                      className="hover:bg-gray-50 dark:hover:bg-gray-800/50 transition-colors cursor-pointer"
                    >
                      <td className="px-4 py-3 text-gray-500 dark:text-gray-400 whitespace-nowrap text-xs">
                        {new Date(log.created_at).toLocaleString('pt-BR')}
                      </td>
                      <td className="px-4 py-3 text-gray-700 dark:text-gray-300">{log.user_email}</td>
                      <td className="px-4 py-3">
                        <span className={`inline-flex px-2 py-0.5 rounded-full text-xs font-medium ${toneClasses(desc.actionTone)}`}>
                          {desc.actionLabel}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-gray-700 dark:text-gray-200 text-sm">
                        {desc.resourceLabel}
                      </td>
                      <td className="px-4 py-3 text-gray-500 dark:text-gray-400 text-xs max-w-md">
                        <div className="line-clamp-2">{desc.summary}</div>
                      </td>
                    </tr>
                  )
                })}
                {data?.items.length === 0 && (
                  <tr>
                    <td colSpan={5} className="px-4 py-12 text-center text-sm text-gray-400 dark:text-gray-600">
                      Nenhum registro encontrado.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          )}
        </div></Card>

        {/* Pagination */}
        {data && data.pages > 1 && (
          <div className="flex items-center justify-between mt-4 text-sm text-gray-500 dark:text-gray-400">
            <span>{data.total} registros</span>
            <div className="flex gap-2">
              <button
                onClick={() => setPage(p => Math.max(1, p - 1))}
                disabled={page === 1}
                className="px-3 py-1.5 rounded-lg border border-gray-200 dark:border-gray-700 disabled:opacity-40 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
              >
                ← Anterior
              </button>
              <span className="px-3 py-1.5">Página {page} de {data.pages}</span>
              <button
                onClick={() => setPage(p => Math.min(data.pages, p + 1))}
                disabled={page === data.pages}
                className="px-3 py-1.5 rounded-lg border border-gray-200 dark:border-gray-700 disabled:opacity-40 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
              >
                Próxima →
              </button>
            </div>
          </div>
        )}
      </div>

      <AuditDetailDrawer log={selected} onClose={() => setSelected(null)} />
    </AppLayout>
  )
}
