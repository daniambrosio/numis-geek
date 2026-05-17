import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowRight, Eye, EyeOff } from 'lucide-react'
import { api, setToken } from '../lib/api'
import { Card, Field, ToggleSwitch, INPUT_CLS } from '../components/ui'

export default function Login() {
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [rememberMe, setRememberMe] = useState(true)
  const [showPass, setShowPass] = useState(false)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const valid = email.includes('@') && password.length >= 1

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!valid) return
    setError('')
    setLoading(true)
    try {
      const { access_token } = await api.login(email, password, rememberMe)
      setToken(access_token, rememberMe)
      navigate('/dashboard')
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Erro ao fazer login')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen w-screen flex items-center justify-center p-6 relative overflow-hidden bg-gray-50 dark:bg-gray-950">
      {/* Subtle gradient backdrop */}
      <div aria-hidden className="absolute inset-0 pointer-events-none">
        <div
          className="absolute -top-32 -left-32 w-96 h-96 rounded-full opacity-20 blur-3xl"
          style={{ background: 'radial-gradient(circle, #6366f1 0%, transparent 70%)' }}
        />
        <div
          className="absolute -bottom-32 -right-32 w-96 h-96 rounded-full opacity-15 blur-3xl"
          style={{ background: 'radial-gradient(circle, #a78bfa 0%, transparent 70%)' }}
        />
      </div>

      <div className="relative w-full max-w-sm">
        {/* Wordmark */}
        <div className="flex items-center justify-center gap-2.5 mb-8">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-indigo-500 to-violet-600 flex items-center justify-center font-bold text-white text-lg">
            N
          </div>
          <div>
            <div className="text-lg font-semibold leading-tight text-gray-900 dark:text-white">Numis-Geek</div>
            <div className="text-[10px] uppercase tracking-wider text-gray-500">finanças pessoais</div>
          </div>
        </div>

        <Card padding="p-6">
          <h1 className="text-base font-semibold text-gray-900 dark:text-white mb-1">Entrar</h1>
          <p className="text-[12px] text-gray-500 dark:text-gray-400">Acesse sua workspace.</p>

          <form className="mt-5 space-y-4" onSubmit={handleSubmit}>
            <Field label="E-mail">
              <input
                type="email"
                required
                autoFocus
                value={email}
                onChange={e => setEmail(e.target.value)}
                placeholder="seu@email.com"
                className={INPUT_CLS}
              />
            </Field>

            <Field label="Senha">
              <div className="relative">
                <input
                  type={showPass ? 'text' : 'password'}
                  required
                  value={password}
                  onChange={e => setPassword(e.target.value)}
                  placeholder="••••••••"
                  className={`${INPUT_CLS} pr-9`}
                />
                <button
                  type="button"
                  onClick={() => setShowPass(v => !v)}
                  className="absolute right-2 top-1/2 -translate-y-1/2 w-7 h-7 inline-flex items-center justify-center rounded-md text-gray-500 hover:text-gray-700 dark:hover:text-gray-300"
                  title={showPass ? 'Ocultar senha' : 'Mostrar senha'}
                >
                  {showPass ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
                </button>
              </div>
            </Field>

            <ToggleSwitch on={rememberMe} onChange={setRememberMe} label="Manter conectado por 30 dias" />

            {error && (
              <p className="text-[12px] text-red-500 dark:text-red-400">{error}</p>
            )}

            <button
              type="submit"
              disabled={!valid || loading}
              className={`w-full h-10 inline-flex items-center justify-center gap-1.5 rounded-lg text-[13px] font-semibold transition-colors mt-2 ${
                valid && !loading
                  ? 'bg-indigo-500 hover:bg-indigo-400 text-white'
                  : 'bg-gray-200 dark:bg-gray-800 text-gray-500 cursor-not-allowed'
              }`}
            >
              {loading ? 'Entrando…' : (
                <>
                  Entrar <ArrowRight className="w-3.5 h-3.5" />
                </>
              )}
            </button>
          </form>
        </Card>

        <div className="mt-5 text-center text-[11px] text-gray-500">
          v1 · sem signup (single-owner)
        </div>
      </div>
    </div>
  )
}
