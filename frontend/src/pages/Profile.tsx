import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, type UserOut } from '../lib/api'
import AppLayout from '../components/AppLayout'

export default function Profile() {
  const navigate = useNavigate()
  const [user, setUser] = useState<UserOut | null>(null)

  // Name form
  const [name, setName] = useState('')
  const [nameMsg, setNameMsg] = useState('')
  const [nameSaving, setNameSaving] = useState(false)

  // Password form
  const [currentPwd, setCurrentPwd] = useState('')
  const [newPwd, setNewPwd] = useState('')
  const [confirmPwd, setConfirmPwd] = useState('')
  const [pwdMsg, setPwdMsg] = useState('')
  const [pwdSaving, setPwdSaving] = useState(false)

  useEffect(() => {
    api.me().then(u => { setUser(u); setName(u.name ?? '') }).catch(() => navigate('/login'))
  }, [navigate])

  async function handleSaveName(e: React.FormEvent) {
    e.preventDefault()
    setNameMsg('')
    setNameSaving(true)
    try {
      const updated = await api.updateMe(name)
      setUser(updated)
      setNameMsg('Nome atualizado.')
    } catch (err) {
      setNameMsg(err instanceof Error ? err.message : 'Erro ao salvar.')
    } finally {
      setNameSaving(false)
    }
  }

  async function handleChangePassword(e: React.FormEvent) {
    e.preventDefault()
    setPwdMsg('')
    if (newPwd !== confirmPwd) { setPwdMsg('As senhas não coincidem.'); return }
    setPwdSaving(true)
    try {
      await api.changePassword(currentPwd, newPwd)
      setPwdMsg('Senha alterada com sucesso.')
      setCurrentPwd(''); setNewPwd(''); setConfirmPwd('')
    } catch (err) {
      setPwdMsg(err instanceof Error ? err.message : 'Erro ao alterar senha.')
    } finally {
      setPwdSaving(false)
    }
  }

  if (!user) return null

  const roleLabel: Record<string, string> = { admin: 'Administrador', member: 'Membro' }

  return (
    <AppLayout user={user}>
      <div className="max-w-xl space-y-6">
        <h1 className="text-xl font-semibold text-gray-900 dark:text-white">Meu Perfil</h1>

        {/* Read-only info */}
        <section className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-800 p-6 space-y-3">
          <h2 className="text-sm font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide">Informações</h2>
          <dl className="grid grid-cols-2 gap-y-3 text-sm">
            <dt className="text-gray-500 dark:text-gray-400">Email</dt>
            <dd className="text-gray-900 dark:text-white font-medium">{user.email}</dd>
            <dt className="text-gray-500 dark:text-gray-400">Role</dt>
            <dd className="text-gray-900 dark:text-white font-medium">{roleLabel[user.role] ?? user.role}</dd>
            <dt className="text-gray-500 dark:text-gray-400">Membro desde</dt>
            <dd className="text-gray-900 dark:text-white font-medium">{new Date(user.created_at).toLocaleDateString('pt-BR')}</dd>
          </dl>
        </section>

        {/* Name form */}
        <section className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-800 p-6">
          <h2 className="text-sm font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-4">Nome</h2>
          <form onSubmit={handleSaveName} className="flex gap-3">
            <input
              type="text"
              value={name}
              onChange={e => setName(e.target.value)}
              placeholder="Seu nome"
              className="flex-1 px-3.5 py-2 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
            <button
              type="submit"
              disabled={nameSaving}
              className="px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-700 disabled:opacity-60 text-white text-sm font-medium transition-colors"
            >
              {nameSaving ? 'Salvando…' : 'Salvar'}
            </button>
          </form>
          {nameMsg && <p className="mt-2 text-sm text-indigo-600 dark:text-indigo-400">{nameMsg}</p>}
        </section>

        {/* Password form */}
        <section className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-800 p-6">
          <h2 className="text-sm font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-4">Alterar Senha</h2>
          <form onSubmit={handleChangePassword} className="space-y-3">
            {[
              { label: 'Senha atual', value: currentPwd, set: setCurrentPwd },
              { label: 'Nova senha', value: newPwd, set: setNewPwd },
              { label: 'Confirmar nova senha', value: confirmPwd, set: setConfirmPwd },
            ].map(({ label, value, set }) => (
              <div key={label}>
                <label className="block text-sm text-gray-700 dark:text-gray-300 mb-1">{label}</label>
                <input
                  type="password"
                  required
                  value={value}
                  onChange={e => set(e.target.value)}
                  className="w-full px-3.5 py-2 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                />
              </div>
            ))}
            {pwdMsg && <p className="text-sm text-indigo-600 dark:text-indigo-400">{pwdMsg}</p>}
            <button
              type="submit"
              disabled={pwdSaving}
              className="px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-700 disabled:opacity-60 text-white text-sm font-medium transition-colors"
            >
              {pwdSaving ? 'Alterando…' : 'Alterar Senha'}
            </button>
          </form>
        </section>
      </div>
    </AppLayout>
  )
}
