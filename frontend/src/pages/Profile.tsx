import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, type UserOut } from '../lib/api'
import AppLayout from '../components/AppLayout'
import { Card, PageHeader, SectionTitle, Field, INPUT_CLS } from '../components/ui'

const ROLE_LABELS: Record<string, string> = {
  sysadmin: 'Sysadmin',
  admin: 'Administrador',
  member: 'Membro',
}

export default function Profile() {
  const navigate = useNavigate()
  const [user, setUser] = useState<UserOut | null>(null)

  const [name, setName] = useState('')
  const [nameMsg, setNameMsg] = useState('')
  const [nameSaving, setNameSaving] = useState(false)

  const [currentPwd, setCurrentPwd] = useState('')
  const [newPwd, setNewPwd] = useState('')
  const [confirmPwd, setConfirmPwd] = useState('')
  const [pwdMsg, setPwdMsg] = useState('')
  const [pwdErr, setPwdErr] = useState(false)
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
    setPwdMsg(''); setPwdErr(false)
    if (newPwd !== confirmPwd) { setPwdMsg('As senhas não coincidem.'); setPwdErr(true); return }
    setPwdSaving(true)
    try {
      await api.changePassword(currentPwd, newPwd)
      setPwdMsg('Senha alterada com sucesso.')
      setCurrentPwd(''); setNewPwd(''); setConfirmPwd('')
    } catch (err) {
      setPwdMsg(err instanceof Error ? err.message : 'Erro ao alterar senha.')
      setPwdErr(true)
    } finally {
      setPwdSaving(false)
    }
  }

  if (!user) return null

  return (
    <AppLayout user={user}>
      <div className="max-w-2xl space-y-6">
        <PageHeader title="Meu Perfil" />

        <Card>
          <SectionTitle>Conta</SectionTitle>
          <dl className="grid grid-cols-2 gap-y-3 text-[13px]">
            <dt className="text-gray-500 dark:text-gray-400">Nome</dt>
            <dd className="text-gray-900 dark:text-white font-medium">
              {user.name ?? <span className="text-gray-400 dark:text-gray-600 italic">não definido</span>}
            </dd>
            <dt className="text-gray-500 dark:text-gray-400">Email</dt>
            <dd className="text-gray-900 dark:text-white font-medium font-mono text-[12px]">{user.email}</dd>
            <dt className="text-gray-500 dark:text-gray-400">Role</dt>
            <dd>
              <span className="inline-flex items-center px-2 py-0.5 rounded-md text-[10px] font-semibold uppercase tracking-wider bg-indigo-500/15 text-indigo-700 dark:text-indigo-300">
                {ROLE_LABELS[user.role] ?? user.role}
              </span>
            </dd>
            <dt className="text-gray-500 dark:text-gray-400">Membro desde</dt>
            <dd className="text-gray-900 dark:text-white font-medium tnum">
              {new Date(user.created_at).toLocaleDateString('pt-BR')}
            </dd>
          </dl>
        </Card>

        <Card>
          <SectionTitle>Atualizar nome</SectionTitle>
          <form onSubmit={handleSaveName} className="flex gap-3">
            <input
              type="text"
              value={name}
              onChange={e => setName(e.target.value)}
              placeholder="Seu nome"
              className={INPUT_CLS}
            />
            <button
              type="submit"
              disabled={nameSaving}
              className="h-9 px-4 inline-flex items-center rounded-lg bg-indigo-500 hover:bg-indigo-400 disabled:opacity-60 text-white text-[12px] font-medium transition-colors"
            >
              {nameSaving ? 'Salvando…' : 'Salvar'}
            </button>
          </form>
          {nameMsg && <p className="mt-2 text-[12px] text-indigo-500 dark:text-indigo-400">{nameMsg}</p>}
        </Card>

        <Card>
          <SectionTitle>Alterar senha</SectionTitle>
          <form onSubmit={handleChangePassword} className="space-y-3">
            <Field label="Senha atual">
              <input
                type="password"
                required
                value={currentPwd}
                onChange={e => setCurrentPwd(e.target.value)}
                className={INPUT_CLS}
              />
            </Field>
            <Field label="Nova senha">
              <input
                type="password"
                required
                value={newPwd}
                onChange={e => setNewPwd(e.target.value)}
                className={INPUT_CLS}
              />
            </Field>
            <Field label="Confirmar nova senha">
              <input
                type="password"
                required
                value={confirmPwd}
                onChange={e => setConfirmPwd(e.target.value)}
                className={INPUT_CLS}
              />
            </Field>
            {pwdMsg && (
              <p className={`text-[12px] ${pwdErr ? 'text-red-500 dark:text-red-400' : 'text-emerald-500 dark:text-emerald-400'}`}>
                {pwdMsg}
              </p>
            )}
            <button
              type="submit"
              disabled={pwdSaving}
              className="h-9 px-4 inline-flex items-center rounded-lg bg-indigo-500 hover:bg-indigo-400 disabled:opacity-60 text-white text-[12px] font-medium transition-colors"
            >
              {pwdSaving ? 'Alterando…' : 'Alterar senha'}
            </button>
          </form>
        </Card>
      </div>
    </AppLayout>
  )
}
