import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, type UserOut } from '../../lib/api'
import AppLayout from '../../components/AppLayout'

interface InviteForm { email: string; name: string; password: string; role: string }

export default function AdminUsers() {
  const navigate = useNavigate()
  const [me, setMe] = useState<UserOut | null>(null)
  const [users, setUsers] = useState<UserOut[]>([])
  const [loading, setLoading] = useState(true)
  const [showInvite, setShowInvite] = useState(false)
  const [form, setForm] = useState<InviteForm>({ email: '', name: '', password: '', role: 'member' })
  const [inviteError, setInviteError] = useState('')
  const [inviteSaving, setInviteSaving] = useState(false)

  useEffect(() => {
    api.me()
      .then(u => setMe(u))
      .catch(() => navigate('/login'))
  }, [navigate])

  useEffect(() => {
    if (!me) return
    api.listUsers()
      .then(u => setUsers(u))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [me])

  async function handleInvite(e: React.FormEvent) {
    e.preventDefault()
    setInviteError('')
    setInviteSaving(true)
    try {
      const u = await api.inviteUser(form)
      setUsers(prev => [...prev, u])
      setShowInvite(false)
      setForm({ email: '', name: '', password: '', role: 'member' })
    } catch (err) {
      setInviteError(err instanceof Error ? err.message : 'Erro ao convidar.')
    } finally {
      setInviteSaving(false)
    }
  }

  async function handleRoleChange(userId: string, role: string) {
    const u = await api.changeRole(userId, role)
    setUsers(prev => prev.map(x => x.id === userId ? u : x))
  }

  async function handleDeactivate(userId: string) {
    if (!confirm('Desativar este usuário?')) return
    const u = await api.deactivateUser(userId)
    setUsers(prev => prev.map(x => x.id === userId ? u : x))
  }

  if (loading || !me) return null

  return (
    <AppLayout user={me}>
      <div className="max-w-3xl">
        <div className="flex items-center justify-between mb-6">
          <h1 className="text-xl font-semibold text-gray-900 dark:text-white">Usuários</h1>
          <button
            onClick={() => setShowInvite(true)}
            className="px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-700 text-white text-sm font-medium transition-colors"
          >
            + Convidar usuário
          </button>
        </div>

        {/* Users table */}
        <div className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-800 overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-200 dark:border-gray-800">
                <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide">Nome / Email</th>
                {me.role === 'sysadmin' && (
                  <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide">Workspace</th>
                )}
                <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide">Role</th>
                <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide">Status</th>
                <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide">Ações</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
              {users.map(u => (
                <tr key={u.id} className="hover:bg-gray-50 dark:hover:bg-gray-800/50 transition-colors">
                  <td className="px-4 py-3">
                    <p className="font-medium text-gray-900 dark:text-white">{u.name ?? '—'}</p>
                    <p className="text-gray-500 dark:text-gray-400 text-xs">{u.email}</p>
                  </td>
                  {me.role === 'sysadmin' && (
                    <td className="px-4 py-3 text-gray-500 dark:text-gray-400 text-xs">
                      {u.workspace_name ?? <span className="text-gray-300 dark:text-gray-600">—</span>}
                    </td>
                  )}
                  <td className="px-4 py-3">
                    {u.role === 'sysadmin' ? (
                      <span className="inline-flex px-2 py-0.5 rounded-full text-xs font-medium bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400">
                        SysAdmin
                      </span>
                    ) : (
                      <select
                        value={u.role}
                        onChange={e => handleRoleChange(u.id, e.target.value)}
                        disabled={u.id === me.id}
                        className="text-xs px-2 py-1 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-300 disabled:opacity-50"
                      >
                        <option value="admin">Admin</option>
                        <option value="member">Member</option>
                      </select>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <span className={`inline-flex px-2 py-0.5 rounded-full text-xs font-medium ${
                      u.is_active
                        ? 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400'
                        : 'bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-500'
                    }`}>
                      {u.is_active ? 'Ativo' : 'Inativo'}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    {u.is_active && u.id !== me.id && u.role !== 'sysadmin' && (
                      <button
                        onClick={() => handleDeactivate(u.id)}
                        className="text-xs text-red-600 dark:text-red-400 hover:underline"
                      >
                        Desativar
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Invite modal */}
      {showInvite && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-800 w-full max-w-md p-6">
            <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">Convidar usuário</h2>
            <form onSubmit={handleInvite} className="space-y-3">
              {[
                { label: 'Email', type: 'email', key: 'email' as const },
                { label: 'Nome (opcional)', type: 'text', key: 'name' as const },
                { label: 'Senha inicial', type: 'password', key: 'password' as const },
              ].map(({ label, type, key }) => (
                <div key={key}>
                  <label className="block text-sm text-gray-700 dark:text-gray-300 mb-1">{label}</label>
                  <input
                    type={type}
                    required={key !== 'name'}
                    value={form[key]}
                    onChange={e => setForm(f => ({ ...f, [key]: e.target.value }))}
                    className="w-full px-3.5 py-2 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  />
                </div>
              ))}
              <div>
                <label className="block text-sm text-gray-700 dark:text-gray-300 mb-1">Role</label>
                <select
                  value={form.role}
                  onChange={e => setForm(f => ({ ...f, role: e.target.value }))}
                  className="w-full px-3.5 py-2 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm"
                >
                  <option value="member">Member</option>
                  <option value="admin">Admin</option>
                </select>
              </div>
              {inviteError && <p className="text-sm text-red-600 dark:text-red-400">{inviteError}</p>}
              <div className="flex gap-3 pt-2">
                <button
                  type="button"
                  onClick={() => setShowInvite(false)}
                  className="flex-1 px-4 py-2 rounded-lg border border-gray-300 dark:border-gray-700 text-gray-700 dark:text-gray-300 text-sm hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
                >
                  Cancelar
                </button>
                <button
                  type="submit"
                  disabled={inviteSaving}
                  className="flex-1 px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-700 disabled:opacity-60 text-white text-sm font-medium transition-colors"
                >
                  {inviteSaving ? 'Convidando…' : 'Convidar'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </AppLayout>
  )
}
