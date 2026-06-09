import { useEffect, useRef, useState, Fragment } from 'react'
import { Link, useNavigate, useLocation } from 'react-router-dom'
import {
  LayoutDashboard, TrendingUp, Compass, LineChart, ArrowDownUp, Coins, Wallet,
  CreditCard, FileText, Target, Building2, Layers, ScrollText, ShieldCheck,
  ChevronDown, Search, Plus, Sun, Moon, Monitor, Eye, EyeOff,
  Plug, DollarSign, Sparkles, ClipboardCheck, Sigma,
} from 'lucide-react'
import { getTheme, applyTheme, type Theme } from '../lib/theme'
import { getPrivacy, togglePrivacy } from '../lib/privacy'
import { getComfort, toggleComfort } from '../lib/comfort'
import { clearToken, type UserOut } from '../lib/api'
import { useInReviewSnapshot } from '../lib/useInReviewSnapshot'
import PriceRefresh from './PriceRefresh'
import VersionMismatchBanner from './VersionMismatchBanner'

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
  { kind: 'item', label: 'Patrimônio', href: '/portfolio', icon: TrendingUp },
  { kind: 'item', label: 'Decision-support', href: '/decision-support', icon: Compass, placeholder: true },
  { kind: 'item', label: 'Ativos', href: '/assets', icon: LineChart },
  { kind: 'item', label: 'Lançamentos', href: '/asset-movements', icon: ArrowDownUp },
  { kind: 'item', label: 'Proventos', href: '/distributions', icon: Coins },
  { kind: 'item', label: 'Fechamentos', href: '/snapshots', icon: ClipboardCheck },

  { kind: 'section', label: 'Caixa & Cartões' },
  { kind: 'item', label: 'Movimentações', href: '/transactions', icon: Wallet, placeholder: true },
  { kind: 'item', label: 'Cartões', href: '/credit-cards', icon: CreditCard, placeholder: true },
  { kind: 'item', label: 'Faturas', href: '/invoices', icon: FileText, placeholder: true },
  { kind: 'item', label: 'Orçamento', href: '/budget', icon: Target, placeholder: true },

  { kind: 'section', label: 'Estrutura' },
  { kind: 'item', label: 'Instituições', href: '/financial-institutions', icon: Building2, placeholder: true },
  { kind: 'item', label: 'Contas', href: '/accounts', icon: Layers },

  { kind: 'section', label: 'Admin', roles: ['admin', 'sysadmin'] },
  { kind: 'item', label: 'Auditoria', href: '/admin/audit', icon: ScrollText },

  { kind: 'section', label: 'Sistema', roles: ['sysadmin'] },
  { kind: 'item', label: 'Usuários', href: '/admin/users', icon: ShieldCheck },
  { kind: 'item', label: 'Inst. Financeiras', href: '/sysadmin/financial-institutions', icon: Building2 },
  { kind: 'item', label: 'Ativos', href: '/sysadmin/assets', icon: LineChart },
  { kind: 'item', label: 'Integrações', href: '/sysadmin/integrations', icon: Plug },
  { kind: 'item', label: 'PTAX', href: '/sysadmin/ptax', icon: DollarSign },
]

type NovoGroup = 'Investimentos' | 'Caixa & Cartões' | 'Cadastros'

interface NovoItem {
  key: string
  label: string
  desc: string
  icon: typeof LayoutDashboard
  group: NovoGroup
  shortcut: string
  enabled: boolean
  /** Route to navigate to and set `?compose=<key>` on. Required when `enabled`. */
  composeRoute?: string
}

// Mirrors prototype index.html:1115-1124. Order within each group preserved.
// "Opção" (Spec 36) sits between Lançamento and Provento — the canonical
// compound-create entry inside Investimentos.
const NOVO_ITEMS: NovoItem[] = [
  { key: 'movement',     label: 'Lançamento',           desc: 'Compra, venda, bonificação…',           icon: ArrowDownUp,  group: 'Investimentos',    shortcut: 'L', enabled: true, composeRoute: '/asset-movements' },
  { key: 'option',       label: 'Opção',                desc: 'PUT/CALL: cria + lança abertura',       icon: Sigma,        group: 'Investimentos',    shortcut: 'O', enabled: true, composeRoute: '/asset-movements' },
  { key: 'distribution', label: 'Provento',             desc: 'Dividendo, juros, JCP, aluguel',        icon: Coins,        group: 'Investimentos',    shortcut: 'P', enabled: true, composeRoute: '/distributions' },
  { key: 'transaction',  label: 'Movimentação',         desc: 'Cash flow em conta corrente',           icon: Wallet,       group: 'Caixa & Cartões',  shortcut: 'M', enabled: false },
  { key: 'card-tx',      label: 'Lançamento de cartão', desc: 'Compra na fatura aberta',               icon: CreditCard,   group: 'Caixa & Cartões',  shortcut: 'F', enabled: false },
  { key: 'asset',        label: 'Ativo',                desc: 'Cadastrar um novo ativo',               icon: LineChart,    group: 'Cadastros',        shortcut: 'A', enabled: true, composeRoute: '/assets' },
  { key: 'account',      label: 'Conta',                desc: 'Nova conta corrente ou de investimento',icon: Layers,       group: 'Cadastros',        shortcut: 'C', enabled: false },
  { key: 'card',         label: 'Cartão',               desc: 'Novo cartão de crédito',                icon: CreditCard,   group: 'Cadastros',        shortcut: 'K', enabled: false },
]

const NOVO_GROUPS: NovoGroup[] = ['Investimentos', 'Caixa & Cartões', 'Cadastros']

function defaultNovoItem(pathname: string): string {
  if (pathname.startsWith('/asset-movements')) return 'movement'
  if (pathname.startsWith('/distributions'))   return 'distribution'
  if (pathname.startsWith('/transactions'))    return 'transaction'
  if (pathname.startsWith('/credit-cards') || pathname.startsWith('/invoices')) return 'card-tx'
  if (pathname.startsWith('/assets'))          return 'asset'
  if (pathname.startsWith('/accounts'))        return 'account'
  return 'movement'
}

export default function AppLayout({ user, children }: Props) {
  const navigate = useNavigate()
  const location = useLocation()
  const [theme, setTheme] = useState<Theme>(getTheme)
  const [privacy, setPrivacy] = useState(getPrivacy)
  const [comfort, setComfort] = useState(getComfort)
  const [avatarOpen, setAvatarOpen] = useState(false)
  const [novoOpen, setNovoOpen] = useState(false)
  const [novoToast, setNovoToast] = useState<string | null>(null)
  const avatarRef = useRef<HTMLDivElement>(null)
  const novoRef = useRef<HTMLDivElement>(null)
  const novoDefault = defaultNovoItem(location.pathname)
  const inReview = useInReviewSnapshot()

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

  function handleNovoClick(item: NovoItem) {
    if (!item.enabled || !item.composeRoute) {
      setNovoToast(item.label)
      window.setTimeout(() => setNovoToast(null), 1400)
      return
    }
    setNovoOpen(false)
    navigate(`${item.composeRoute}?compose=${item.key}`)
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
            <div className="text-[10px] uppercase tracking-wider text-gray-500">
              v{__APP_VERSION__}
            </div>
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
                {n.href === '/snapshots' && inReview && (
                  <span
                    className="inline-flex items-center justify-center w-4 h-4 rounded-full bg-amber-500 text-white text-[9px] font-bold"
                    title="Fechamento em revisão"
                    data-testid="sidebar-snapshot-badge"
                  >
                    !
                  </span>
                )}
                {n.placeholder && (
                  <span className="text-[9px] uppercase tracking-wider text-gray-500 dark:text-gray-600">soon</span>
                )}
              </Link>
            )
          })}
        </nav>

        {/* Spec 54 — build version footer (sempre visível). */}
        <div
          className="border-t border-gray-200 dark:border-gray-800 px-5 py-2 text-[10px] text-gray-500 tnum"
          title={`Versão ${__APP_VERSION__} · build ${__APP_SHA__} · ${__APP_BUILD_DATE__}`}
          data-testid="sidebar-version-footer"
        >
          <div>v{__APP_VERSION__} · {__APP_SHA__}</div>
          <div className="text-[9px]">{__APP_BUILD_DATE__}</div>
        </div>
      </aside>

      {/* Main column */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Spec 54 — banner de mismatch backend↔frontend. */}
        <VersionMismatchBanner />
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
            {/* Price refresh (Spec 25) */}
            <PriceRefresh />

            {/* Novo */}
            <div className="relative" ref={novoRef}>
              <button
                onClick={() => setNovoOpen(o => !o)}
                className="h-8 px-3 inline-flex items-center gap-1.5 rounded-lg bg-indigo-500 hover:bg-indigo-400 text-white text-[12px] font-medium transition-colors"
              >
                <Plus className="w-3.5 h-3.5" /> Novo
                <ChevronDown className="w-3 h-3 -mr-0.5 opacity-80" />
              </button>
              {novoOpen && (
                <div className="menu-pop absolute right-0 mt-2 w-72 rounded-xl bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 shadow-2xl shadow-black/30 p-2 z-50">
                  {NOVO_GROUPS.map(g => (
                    <Fragment key={g}>
                      <div className="px-2 pt-2 pb-1 text-[10px] uppercase tracking-wider font-semibold text-gray-500 dark:text-gray-400">{g}</div>
                      {NOVO_ITEMS.filter(it => it.group === g).map(item => {
                        const isDefault = item.key === novoDefault
                        const Icon = item.icon
                        return (
                          <button
                            key={item.key}
                            onClick={() => handleNovoClick(item)}
                            title={item.enabled ? '' : 'Em breve'}
                            className={`w-full text-left flex items-start gap-2.5 px-2 py-1.5 rounded-md transition-colors ${
                              isDefault
                                ? 'bg-indigo-500/10 hover:bg-indigo-500/15'
                                : 'hover:bg-gray-100 dark:hover:bg-gray-800/50'
                            } ${!item.enabled ? 'opacity-60' : ''}`}
                          >
                            <Icon className={`w-4 h-4 mt-0.5 shrink-0 ${isDefault ? 'text-indigo-500 dark:text-indigo-400' : 'text-gray-500 dark:text-gray-400'}`} />
                            <div className="flex-1 min-w-0">
                              <div className="flex items-center gap-1.5">
                                <span className={`text-[12px] font-medium ${isDefault ? 'text-indigo-700 dark:text-indigo-300' : 'text-gray-700 dark:text-gray-200'}`}>
                                  {item.label}
                                </span>
                                {isDefault && <Sparkles className="w-3 h-3 text-indigo-500 dark:text-indigo-400" />}
                                {!item.enabled && <span className="text-[9px] uppercase tracking-wider text-gray-400 dark:text-gray-600">em breve</span>}
                              </div>
                              <div className="text-[11px] text-gray-500 dark:text-gray-500 truncate">{item.desc}</div>
                            </div>
                            <kbd className="text-[9px] text-gray-500 dark:text-gray-400 px-1 py-0.5 rounded bg-gray-100 dark:bg-gray-800/50 shrink-0">
                              {item.shortcut}
                            </kbd>
                          </button>
                        )
                      })}
                    </Fragment>
                  ))}
                  <div className="mt-2 pt-2 border-t border-gray-100 dark:border-gray-800 px-2 py-1 text-[10px] text-gray-500 dark:text-gray-400 inline-flex items-center gap-1">
                    <Sparkles className="w-3 h-3 text-indigo-500 dark:text-indigo-400" />
                    sugerido pelo contexto atual
                  </div>
                </div>
              )}
              {novoToast && (
                <div className="menu-pop absolute right-0 -bottom-10 px-2.5 py-1 rounded-md bg-gray-900 dark:bg-gray-100 text-white dark:text-gray-900 text-[11px] shadow-lg z-50 whitespace-nowrap">
                  {novoToast} — em breve
                </div>
              )}
            </div>

            {/* Comfort */}
            <button
              onClick={() => setComfort(toggleComfort())}
              title={comfort ? 'Conforto: ligado' : 'Conforto: desligado'}
              aria-pressed={comfort}
              className={`h-8 px-2 inline-flex items-center justify-center rounded-lg transition-colors leading-none ${
                comfort
                  ? 'bg-indigo-500/15 text-indigo-700 dark:text-indigo-300 hover:bg-indigo-500/25'
                  : 'text-gray-500 hover:text-gray-700 dark:hover:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-800'
              }`}
            >
              <span className="inline-flex items-baseline gap-0.5">
                <span className="text-[10px] font-bold leading-none">A</span>
                <span className={`font-bold leading-none ${comfort ? 'text-[15px]' : 'text-[12px]'}`}>A</span>
              </span>
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
