import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useLocation } from 'react-router-dom'
import {
  LayoutDashboard, TrendingUp, LineChart, ArrowDownUp, Coins, Wallet,
  CreditCard, FileText, Target, Building2, Layers, ScrollText, ShieldCheck,
  ChevronDown, Search, Plus, Sun, Moon, Monitor, Eye, EyeOff,
  Plug, DollarSign,
} from 'lucide-react'
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
  kind: 'item'
  label: string
  href: string
  icon: typeof LayoutDashboard
  placeholder?: boolean
}

interface NavSection {
  kind: 'section'
  label: string
  roles?: Role[]
}

type NavEntry = NavItem | NavSection

const NAV: NavEntry[] = [
  { kind: 'section', label: 'Workspace' },
  { kind: 'item', label: 'Dashboard', href: '/dashboard', icon: LayoutDashboard },

  { kind: 'section', label: 'Investimentos' },
  { kind: 'item', label: 'Patrimônio', href: '/patrimonio', icon: TrendingUp, placeholder: true },
  { kind: 'item', label: 'Ativos', href: '/assets', icon: LineChart },
  { kind: 'item', label: 'Lançamentos', href: '/lancamentos', icon: ArrowDownUp },
  { kind: 'item', label: 'Proventos', href: '/proventos', icon: Coins, placeholder: true },

  { kind: 'section', label: 'Caixa & Cartões' },
  { kind: 'item', label: 'Movimentações', href: '/movimentacoes', icon: Wallet, placeholder: true },
  { kind: 'item', label: 'Cartões', href: '/cartoes', icon: CreditCard, placeholder: true },
  { kind: 'item', label: 'Faturas', href: '/faturas', icon: FileText, placeholder: true },
  { kind: 'item', label: 'Orçamento', href: '/orcamento', icon: Target, placeholder: true },

  { kind: 'section', label: 'Estrutura' },
  { kind: 'item', label: 'Instituições', href: '/instituicoes', icon: Building2, placeholder: true },
  { kind: 'item', label: 'Contas', href: '/accounts', icon: Layers },

  { kind: 'section', label: 'Admin', roles: ['admin', 'sysadmin'] },
  { kind: 'item', label: 'Usuários', href: '/admin/users', icon: ShieldCheck },
  { kind: 'item', label: 'Auditoria', href: '/admin/audit', icon: ScrollText },

  { kind: 'section', label: 'Sistema', roles: ['sysadmin'] },
  { kind: 'item', label: 'Inst. Financeiras', href: '/sysadmin/financial-institutions', icon: Building2 },
  { kind: 'item', label: 'Ativos', href: '/sysadmin/assets', icon: LineChart },
  { kind: 'item', label: 'Integrações', href: '/sysadmin/integrations', icon: Plug },
  { kind: 'item', label: 'PTAX', href: '/sysadmin/ptax', icon: DollarSign },
]

const NOVO_ITEMS = ['Lançamento', 'Provento', 'Movimentação', 'Cartão tx', 'Ativo', 'Conta', 'Cartão']

export default function AppLayout({ user, children }: Props) {
  const navigate = useNavigate()
  const location = useLocation()
  const [theme, setTheme] = useState<Theme>(getTheme)
  const [privacy, setPrivacy] = useState(getPrivacy)
  const [comfort, setComfort] = useState(getComfort)
  const [avatarOpen, setAvatarOpen] = useState(false)
  const [novoOpen, setNovoOpen] = useState(false)
  const avatarRef = useRef<HTMLDivElement>(null)
  const novoRef = useRef<HTMLDivElement>(null)

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
  const visibleEntries: NavEntry[] = []
  let skipUntilNextSection = false
  for (const n of NAV) {
    if (n.kind === 'section') {
      skipUntilNextSection = !!(n.roles && !n.roles.includes(role))
      if (!skipUntilNextSection) visibleEntries.push(n)
    } else if (!skipUntilNextSection) {
      visibleEntries.push(n)
    }
  }

  return (
    <div className="flex h-screen bg-gray-50 text-gray-900 dark:bg-gray-950 dark:text-gray-100">
      {/* Sidebar */}
      <aside className="w-60 shrink-0 border-r border-gray-200 dark:border-gray-800 bg-gray-50 dark:bg-gray-950 flex flex-col">
        <div className="px-5 py-5 flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-indigo-500 to-violet-600 flex items-center justify-center font-bold text-white text-[15px]">
            N
          </div>
          <div>
            <div className="text-sm font-semibold leading-tight">Numis-Geek</div>
            <div className="text-[10px] uppercase tracking-wider text-gray-500">v1</div>
          </div>
        </div>

        <div className="px-3 mb-2">
          <button className="w-full flex items-center justify-between px-2.5 py-2 rounded-lg bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 hover:border-gray-300 dark:hover:border-gray-700 transition-colors text-left">
            <div className="flex items-center gap-2 min-w-0">
              <div className="w-5 h-5 rounded bg-indigo-500/20 flex items-center justify-center text-[10px] font-semibold text-indigo-300">FA</div>
              <div className="min-w-0">
                <div className="text-[12px] font-medium truncate">Família Ambrosio</div>
                <div className="text-[10px] text-gray-500">workspace</div>
              </div>
            </div>
            <ChevronDown className="w-3.5 h-3.5 text-gray-500" />
          </button>
        </div>

        <nav className="flex-1 overflow-y-auto scrollbar-thin px-2 pb-4">
          {visibleEntries.map((n, i) => {
            if (n.kind === 'section') {
              return (
                <div key={`s-${i}`} className="px-3 mt-4 mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-gray-500">
                  {n.label}
                </div>
              )
            }
            const active = location.pathname === n.href
            const Icon = n.icon
            return (
              <Link
                key={n.href}
                to={n.href}
                className={`group flex items-center gap-2.5 px-2.5 py-1.5 rounded-md text-[13px] mb-0.5 transition-colors ${
                  active
                    ? 'bg-indigo-500/15 text-indigo-700 dark:text-indigo-300'
                    : 'text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-900/70'
                }`}
              >
                <Icon className="w-4 h-4" strokeWidth={active ? 2.2 : 1.6} />
                <span className="flex-1">{n.label}</span>
                {n.placeholder && (
                  <span className="text-[9px] uppercase tracking-wider text-gray-500 dark:text-gray-600">soon</span>
                )}
              </Link>
            )
          })}
        </nav>
      </aside>

      {/* Main column */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Top bar */}
        <header className="h-14 shrink-0 border-b border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 flex items-center px-4 gap-4">
          {/* Search */}
          <div className="relative max-w-md flex-1">
            <Search className="w-3.5 h-3.5 absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
            <input
              type="text"
              placeholder="Buscar…"
              className="w-full h-8 pl-8 pr-14 text-[12px] rounded-lg bg-gray-100 dark:bg-gray-950 border border-gray-200 dark:border-gray-800 placeholder:text-gray-500 focus:outline-none focus:border-indigo-500"
            />
            <kbd className="absolute right-2 top-1/2 -translate-y-1/2 inline-flex items-center gap-0.5 rounded border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-1.5 py-0.5 text-[10px] font-mono text-gray-400 dark:text-gray-500">
              ⌘K
            </kbd>
          </div>

          {/* Right cluster — flushed via ml-auto */}
          <div className="flex items-center gap-2 ml-auto">
            {/* Novo */}
            <div className="relative" ref={novoRef}>
              <button
                onClick={() => setNovoOpen(o => !o)}
                className="h-8 px-3 inline-flex items-center gap-1.5 rounded-lg bg-indigo-500 hover:bg-indigo-400 text-white text-[12px] font-medium transition-colors"
              >
                <Plus className="w-3.5 h-3.5" /> Novo
              </button>
              {novoOpen && (
                <div className="menu-pop absolute right-0 mt-2 w-52 rounded-xl bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 shadow-lg py-1 z-50">
                  <div className="px-3 py-2 text-[10px] uppercase tracking-wider font-semibold text-gray-400 dark:text-gray-500">Criar</div>
                  {NOVO_ITEMS.map(label => (
                    <button
                      key={label}
                      disabled
                      title="Em breve"
                      className="w-full flex items-center justify-between px-3 py-1.5 text-[12px] text-gray-400 dark:text-gray-600 cursor-not-allowed"
                    >
                      <span>{label}</span>
                      <span className="text-[9px] uppercase tracking-wider">em breve</span>
                    </button>
                  ))}
                </div>
              )}
            </div>

            {/* Comfort */}
            <button
              onClick={() => setComfort(toggleComfort())}
              title={comfort ? 'Conforto: ligado' : 'Conforto: desligado'}
              aria-pressed={comfort}
              className={`h-8 px-2 inline-flex items-end justify-center rounded-lg transition-colors gap-0.5 leading-none ${
                comfort
                  ? 'bg-indigo-500/15 text-indigo-700 dark:text-indigo-300 hover:bg-indigo-500/25'
                  : 'text-gray-500 hover:text-gray-700 dark:hover:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-800'
              }`}
            >
              <span className="text-[10px] font-bold leading-none">A</span>
              <span className={`font-bold leading-none ${comfort ? 'text-[15px]' : 'text-[12px]'}`}>A</span>
            </button>

            {/* Privacy */}
            <button
              onClick={() => setPrivacy(togglePrivacy())}
              title={privacy ? 'Mostrar valores' : 'Ocultar valores'}
              aria-pressed={privacy}
              className={`w-8 h-8 inline-flex items-center justify-center rounded-lg transition-colors ${
                privacy
                  ? 'bg-amber-500/15 text-amber-400 hover:bg-amber-500/25'
                  : 'text-gray-500 hover:text-gray-700 dark:hover:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-800'
              }`}
            >
              {privacy ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
            </button>

            {/* Theme */}
            <div className="inline-flex items-center rounded-lg p-0.5 bg-gray-100 dark:bg-gray-900 border border-gray-200 dark:border-gray-800">
              {([
                { value: 'light' as Theme, title: 'Tema claro', icon: <Sun className="w-3.5 h-3.5" /> },
                { value: 'dark' as Theme, title: 'Tema escuro', icon: <Moon className="w-3.5 h-3.5" /> },
                { value: 'system' as Theme, title: 'Tema do sistema', icon: <Monitor className="w-3.5 h-3.5" /> },
              ]).map(opt => (
                <button
                  key={opt.value}
                  onClick={() => { applyTheme(opt.value); setTheme(opt.value) }}
                  title={opt.title}
                  className={`w-7 h-7 inline-flex items-center justify-center rounded-md transition-colors ${
                    theme === opt.value
                      ? 'bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 shadow-sm'
                      : 'text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'
                  }`}
                >
                  {opt.icon}
                </button>
              ))}
            </div>

            {/* Avatar */}
            <div className="relative" ref={avatarRef}>
              <button
                onClick={() => setAvatarOpen(o => !o)}
                className="w-8 h-8 inline-flex items-center justify-center rounded-full bg-indigo-600 text-white text-[11px] font-semibold hover:bg-indigo-700 transition-colors"
              >
                {initials}
              </button>
              {avatarOpen && (
                <div className="menu-pop absolute right-0 mt-2 w-48 rounded-xl bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 shadow-lg py-1 z-50">
                  <div className="px-3 py-2 border-b border-gray-100 dark:border-gray-800">
                    <p className="text-[11px] font-medium text-gray-900 dark:text-white truncate">{user.name ?? user.email}</p>
                    <p className="text-[10px] text-gray-500 dark:text-gray-400 truncate">{user.email}</p>
                  </div>
                  <Link
                    to="/profile"
                    onClick={() => setAvatarOpen(false)}
                    className="block px-3 py-1.5 text-[12px] text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800"
                  >
                    Meu Perfil
                  </Link>
                  <button
                    onClick={handleLogout}
                    className="w-full text-left px-3 py-1.5 text-[12px] text-red-600 dark:text-red-400 hover:bg-gray-50 dark:hover:bg-gray-800"
                  >
                    Sair
                  </button>
                </div>
              )}
            </div>
          </div>
        </header>

        {/* Content */}
        <main className="flex-1 overflow-y-auto p-6 scrollbar-thin">
          {children}
        </main>
      </div>
    </div>
  )
}
