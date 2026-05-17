import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useLocation } from 'react-router-dom'
import { getTheme, applyTheme, type Theme } from '../lib/theme'
import { getPrivacy, togglePrivacy } from '../lib/privacy'
import { getComfort, toggleComfort } from '../lib/comfort'
import { clearToken, type UserOut } from '../lib/api'

interface Props {
  user: UserOut
  children: React.ReactNode
}

type Role = 'sysadmin' | 'admin' | 'member'

interface NavItem {
  label: string
  href: string
  roles?: Role[]
}

interface NavSection {
  title: string
  items: NavItem[]
  roles?: Role[]
}

const SECTIONS: NavSection[] = [
  {
    title: 'Workspace',
    items: [
      { label: 'Dashboard', href: '/dashboard' },
    ],
  },
  {
    title: 'Investimentos',
    items: [
      { label: 'Patrimônio', href: '/patrimonio' },
      { label: 'Ativos', href: '/assets' },
      { label: 'Lançamentos', href: '/lancamentos' },
      { label: 'Proventos', href: '/proventos' },
    ],
  },
  {
    title: 'Caixa & Cartões',
    items: [
      { label: 'Movimentações', href: '/movimentacoes' },
      { label: 'Cartões', href: '/cartoes' },
      { label: 'Faturas', href: '/faturas' },
      { label: 'Orçamento', href: '/orcamento' },
    ],
  },
  {
    title: 'Estrutura',
    items: [
      { label: 'Instituições', href: '/instituicoes' },
      { label: 'Contas', href: '/accounts' },
    ],
  },
  {
    title: 'Admin',
    roles: ['admin', 'sysadmin'],
    items: [
      { label: 'Usuários', href: '/admin/users' },
      { label: 'Auditoria', href: '/admin/audit' },
    ],
  },
  {
    title: 'Sistema',
    roles: ['sysadmin'],
    items: [
      { label: 'Inst. Financeiras', href: '/sysadmin/financial-institutions' },
      { label: 'Ativos', href: '/sysadmin/assets' },
    ],
  },
]

const NOVO_ITEMS = [
  'Lançamento',
  'Provento',
  'Movimentação',
  'Cartão tx',
  'Ativo',
  'Conta',
  'Cartão',
]

function IconSun() {
  return (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364-6.364l-.707.707M6.343 17.657l-.707.707M17.657 17.657l-.707-.707M6.343 6.343l-.707-.707M12 7a5 5 0 100 10A5 5 0 0012 7z" />
    </svg>
  )
}
function IconMoon() {
  return (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z" />
    </svg>
  )
}
function IconMonitor() {
  return (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
    </svg>
  )
}
function IconEyeOn() {
  return (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
    </svg>
  )
}
function IconEyeOff() {
  return (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21" />
    </svg>
  )
}
function IconBurger() {
  return (
    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
    </svg>
  )
}
function IconSearch() {
  return (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-4.35-4.35M16 11a5 5 0 11-10 0 5 5 0 0110 0z" />
    </svg>
  )
}
function IconPlus() {
  return (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
    </svg>
  )
}

export default function AppLayout({ user, children }: Props) {
  const navigate = useNavigate()
  const location = useLocation()
  const [sidebarOpen, setSidebarOpen] = useState(() => localStorage.getItem('sidebar') !== 'closed')
  const [theme, setTheme] = useState<Theme>(getTheme)
  const [privacy, setPrivacy] = useState(getPrivacy)
  const [comfort, setComfort] = useState(getComfort)
  const [avatarOpen, setAvatarOpen] = useState(false)
  const [novoOpen, setNovoOpen] = useState(false)
  const avatarRef = useRef<HTMLDivElement>(null)
  const novoRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    localStorage.setItem('sidebar', sidebarOpen ? 'open' : 'closed')
  }, [sidebarOpen])

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      const t = e.target as Node
      if (avatarRef.current && !avatarRef.current.contains(t)) setAvatarOpen(false)
      if (novoRef.current && !novoRef.current.contains(t)) setNovoOpen(false)
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [])

  useEffect(() => {
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    function onSystemChange() {
      if (getTheme() === 'system') applyTheme('system')
    }
    mq.addEventListener('change', onSystemChange)
    return () => mq.removeEventListener('change', onSystemChange)
  }, [])

  function handleLogout() {
    clearToken()
    navigate('/login')
  }

  const initials = user.name
    ? user.name.split(' ').map(p => p[0]).join('').slice(0, 2).toUpperCase()
    : user.email[0].toUpperCase()

  const role = user.role as Role
  const visibleSections = SECTIONS.filter(s => !s.roles || s.roles.includes(role))

  return (
    <div className="flex flex-col h-screen bg-gray-50 dark:bg-gray-950">
      {/* Topbar */}
      <header className="flex items-center gap-4 px-4 h-14 border-b border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 shrink-0 z-10">
        {/* Left: burger + brand */}
        <div className="flex items-center gap-3 shrink-0">
          <button
            onClick={() => setSidebarOpen(o => !o)}
            className="p-1.5 rounded-lg text-gray-500 hover:text-gray-900 dark:hover:text-white hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
            title="Toggle sidebar"
          >
            <IconBurger />
          </button>
          <span className="font-semibold text-gray-900 dark:text-white text-sm">Numis-Geek</span>
        </div>

        {/* Center: search (visual only) */}
        <div className="flex-1 max-w-md">
          <div className="relative">
            <span className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 dark:text-gray-600">
              <IconSearch />
            </span>
            <input
              type="text"
              placeholder="Buscar…"
              className="w-full pl-9 pr-14 py-1.5 rounded-lg border border-gray-200 dark:border-gray-800 bg-gray-50 dark:bg-gray-950 text-sm text-gray-700 dark:text-gray-300 placeholder:text-gray-400 dark:placeholder:text-gray-600 focus:outline-none focus:ring-2 focus:ring-indigo-500"
              aria-label="Buscar"
            />
            <kbd className="absolute right-2 top-1/2 -translate-y-1/2 inline-flex items-center gap-0.5 rounded border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-1.5 py-0.5 text-[10px] font-mono text-gray-400 dark:text-gray-500">
              ⌘K
            </kbd>
          </div>
        </div>

        {/* Right: controls flushed right */}
        <div className="flex items-center gap-2 ml-auto shrink-0">
          {/* Novo dropdown */}
          <div className="relative" ref={novoRef}>
            <button
              onClick={() => setNovoOpen(o => !o)}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-700 text-white text-sm font-medium transition-colors"
            >
              <IconPlus />
              Novo
            </button>
            {novoOpen && (
              <div className="absolute right-0 mt-2 w-52 rounded-xl bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 shadow-lg py-1 z-50">
                <div className="px-3 py-2 text-[10px] uppercase tracking-wider font-semibold text-gray-400 dark:text-gray-500">
                  Criar
                </div>
                {NOVO_ITEMS.map(label => (
                  <button
                    key={label}
                    disabled
                    className="w-full flex items-center justify-between px-3 py-2 text-sm text-gray-400 dark:text-gray-600 cursor-not-allowed"
                    title="Em breve"
                  >
                    <span>{label}</span>
                    <span className="text-[10px] text-gray-300 dark:text-gray-700">em breve</span>
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Comfort toggle */}
          <button
            onClick={() => setComfort(toggleComfort())}
            title={comfort ? 'Conforto: ligado' : 'Conforto: desligado'}
            aria-pressed={comfort}
            className={`px-2 py-1.5 rounded-lg text-xs font-semibold transition-colors ${
              comfort
                ? 'bg-indigo-50 dark:bg-indigo-900/40 text-indigo-600 dark:text-indigo-300'
                : 'text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-800'
            }`}
          >
            Aa
          </button>

          {/* Privacy toggle */}
          <button
            onClick={() => setPrivacy(togglePrivacy())}
            title={privacy ? 'Privacidade: ligada' : 'Privacidade: desligada'}
            aria-pressed={privacy}
            className={`p-1.5 rounded-lg transition-colors ${
              privacy
                ? 'bg-indigo-50 dark:bg-indigo-900/40 text-indigo-600 dark:text-indigo-300'
                : 'text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-800'
            }`}
          >
            {privacy ? <IconEyeOff /> : <IconEyeOn />}
          </button>

          {/* Theme segmented */}
          <div className="flex items-center rounded-lg border border-gray-200 dark:border-gray-700 overflow-hidden">
            {([
              { value: 'dark' as Theme, title: 'Modo escuro', icon: <IconMoon /> },
              { value: 'light' as Theme, title: 'Modo claro', icon: <IconSun /> },
              { value: 'system' as Theme, title: 'Seguir sistema', icon: <IconMonitor /> },
            ]).map(opt => (
              <button
                key={opt.value}
                onClick={() => { applyTheme(opt.value); setTheme(opt.value) }}
                title={opt.title}
                className={`p-1.5 transition-colors ${
                  theme === opt.value
                    ? 'bg-indigo-50 dark:bg-indigo-900/40 text-indigo-600 dark:text-indigo-300'
                    : 'text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-800'
                }`}
              >
                {opt.icon}
              </button>
            ))}
          </div>

          {/* Avatar dropdown */}
          <div className="relative" ref={avatarRef}>
            <button
              onClick={() => setAvatarOpen(o => !o)}
              className="flex items-center justify-center w-8 h-8 rounded-full bg-indigo-600 text-white text-xs font-semibold hover:bg-indigo-700 transition-colors"
            >
              {initials}
            </button>
            {avatarOpen && (
              <div className="absolute right-0 mt-2 w-48 rounded-xl bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 shadow-lg py-1 z-50">
                <div className="px-4 py-2 border-b border-gray-100 dark:border-gray-800">
                  <p className="text-xs font-medium text-gray-900 dark:text-white truncate">{user.name ?? user.email}</p>
                  <p className="text-xs text-gray-500 dark:text-gray-400 truncate">{user.email}</p>
                </div>
                <Link
                  to="/profile"
                  onClick={() => setAvatarOpen(false)}
                  className="block px-4 py-2 text-sm text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800"
                >
                  Meu Perfil
                </Link>
                <button
                  onClick={handleLogout}
                  className="w-full text-left px-4 py-2 text-sm text-red-600 dark:text-red-400 hover:bg-gray-50 dark:hover:bg-gray-800"
                >
                  Sair
                </button>
              </div>
            )}
          </div>
        </div>
      </header>

      <div className="flex flex-1 overflow-hidden">
        {/* Sidebar */}
        {sidebarOpen && (
          <aside className="w-60 shrink-0 border-r border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 overflow-y-auto">
            <nav className="p-3 space-y-4">
              {visibleSections.map(section => (
                <div key={section.title}>
                  <div className="px-3 pb-1.5">
                    <span className="text-[10px] font-semibold text-gray-400 dark:text-gray-500 uppercase tracking-wider">
                      {section.title}
                    </span>
                  </div>
                  <div className="space-y-0.5">
                    {section.items.map(item => {
                      const active = location.pathname === item.href
                      return (
                        <Link
                          key={item.href}
                          to={item.href}
                          className={`block px-3 py-1.5 rounded-lg text-sm transition-colors ${
                            active
                              ? 'bg-indigo-50 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-300 font-medium'
                              : 'text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-800 hover:text-gray-900 dark:hover:text-white'
                          }`}
                        >
                          {item.label}
                        </Link>
                      )
                    })}
                  </div>
                </div>
              ))}
            </nav>
          </aside>
        )}

        {/* Content */}
        <main className="flex-1 overflow-y-auto p-6">
          {children}
        </main>
      </div>
    </div>
  )
}
