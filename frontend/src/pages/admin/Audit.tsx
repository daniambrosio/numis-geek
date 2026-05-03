import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, type AuditLogOut, type AuditPage, type UserOut } from '../../lib/api'
import AppLayout from '../../components/AppLayout'

const ACTION_OPTIONS = [
  '', 'auth.login', 'user.invited', 'user.role_changed', 'user.deactivated',
  'profile.name_changed', 'profile.password_changed',
  'financial_institution.created', 'financial_institution.updated', 'financial_institution.deactivated',
]

function actionLabel(action: string): string {
  const map: Record<string, string> = {
    'auth.login': 'Login',
    'user.invited': 'Usuário convidado',
    'user.role_changed': 'Role alterada',
    'user.deactivated': 'Usuário desativado',
    'profile.name_changed': 'Nome alterado',
    'profile.password_changed': 'Senha alterada',
    'financial_institution.created': 'IF criada',
    'financial_institution.updated': 'IF atualizada',
    'financial_institution.deactivated': 'IF desativada',
  }
  return map[action] ?? action
}

function actionColor(action: string): string {
  if (action.startsWith('auth.')) return 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400'
  if (action.startsWith('user.')) return 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400'
  if (action.startsWith('profile.')) return 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400'
  if (action.startsWith('financial_institution.')) return 'bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400'
  return 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400'
}

export default function AdminAudit() {
  const navigate = useNavigate()
  const [me, setMe] = useState<UserOut | null>(null)
  const [data, setData] = useState<AuditPage | null>(null)
  const [page, setPage] = useState(1)
  const [actionFilter, setActionFilter] = useState('')
  const [loading, setLoading] = useState(true)

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
      <div className="w-full">
        <div className="flex items-center justify-between mb-6">
          <h1 className="text-xl font-semibold text-gray-900 dark:text-white">Auditoria</h1>
          <select
            value={actionFilter}
            onChange={e => handleFilterChange(e.target.value)}
            className="text-sm px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-300"
          >
            <option value="">Todas as ações</option>
            {ACTION_OPTIONS.filter(Boolean).map(a => (
              <option key={a} value={a}>{actionLabel(a)}</option>
            ))}
          </select>
        </div>

        <div className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-800 overflow-hidden">
          {loading ? (
            <div className="p-12 text-center text-sm text-gray-400 dark:text-gray-600">Carregando…</div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-200 dark:border-gray-800">
                  {['Data', 'Usuário', 'Ação', 'Recurso'].map(h => (
                    <th key={h} className="text-left px-4 py-3 text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
                {data?.items.map((log: AuditLogOut) => (
                  <tr key={log.id} className="hover:bg-gray-50 dark:hover:bg-gray-800/50 transition-colors">
                    <td className="px-4 py-3 text-gray-500 dark:text-gray-400 whitespace-nowrap text-xs">
                      {new Date(log.created_at).toLocaleString('pt-BR')}
                    </td>
                    <td className="px-4 py-3 text-gray-700 dark:text-gray-300">{log.user_email}</td>
                    <td className="px-4 py-3">
                      <span className={`inline-flex px-2 py-0.5 rounded-full text-xs font-medium ${actionColor(log.action)}`}>
                        {actionLabel(log.action)}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-gray-500 dark:text-gray-400 text-xs">
                      {log.resource_type && <span>{log.resource_type}{log.resource_id ? ` · ${log.resource_id.slice(0, 8)}…` : ''}</span>}
                    </td>
                  </tr>
                ))}
                {data?.items.length === 0 && (
                  <tr>
                    <td colSpan={4} className="px-4 py-12 text-center text-sm text-gray-400 dark:text-gray-600">
                      Nenhum registro encontrado.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          )}
        </div>

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
    </AppLayout>
  )
}
