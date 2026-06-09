import type { AuditLogOut } from './api'

export type AuditTone =
  | 'auth'
  | 'user'
  | 'profile'
  | 'account'
  | 'fi'
  | 'asset'
  | 'price'
  | 'movement'
  | 'distribution'
  | 'attachment'
  | 'snapshot'
  | 'pendency'
  | 'extraction'
  | 'integration'
  | 'api'
  | 'generic'

export interface AuditDescription {
  actionLabel: string
  actionTone: AuditTone
  resourceLabel: string
  summary: string
  link?: { to: string; label: string }
}

interface ParsedAudit {
  action: string
  resourceType: string | null
  resourceId: string | null
  details: Record<string, unknown>
}

function parseDetails(raw: string | null | undefined): Record<string, unknown> {
  if (!raw) return {}
  try {
    const v = JSON.parse(raw)
    return v && typeof v === 'object' ? (v as Record<string, unknown>) : {}
  } catch {
    return {}
  }
}

function str(v: unknown): string | null {
  return typeof v === 'string' && v.length > 0 ? v : null
}

function num(v: unknown): number | null {
  if (typeof v === 'number' && Number.isFinite(v)) return v
  if (typeof v === 'string' && v.length > 0) {
    const n = Number(v)
    return Number.isFinite(n) ? n : null
  }
  return null
}

function ymOf(dateLike: unknown): string | null {
  const s = str(dateLike)
  if (!s) return null
  const m = s.match(/^(\d{4})-(\d{2})/)
  return m ? `${m[1]}-${m[2]}` : null
}

function fmtBRL(v: unknown, fallback = '—'): string {
  const n = num(v)
  if (n == null) return fallback
  return n.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })
}

function fmtNumber(v: unknown, decimals = 2, fallback = '—'): string {
  const n = num(v)
  if (n == null) return fallback
  return n.toLocaleString('pt-BR', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })
}

function fmtBytes(v: unknown): string {
  const n = num(v)
  if (n == null) return '—'
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

function shortId(id: string | null | undefined): string {
  return id ? `${id.slice(0, 8)}…` : ''
}

const CLASS_LABEL: Record<string, string> = {
  STOCK: 'Ação',
  REIT: 'FII',
  ETF: 'ETF',
  BDR: 'BDR',
  FIXED_INCOME: 'Renda fixa',
  FUND: 'Fundo',
  REAL_ESTATE: 'Imóvel',
  VEHICLE: 'Veículo',
  PRIVATE_PENSION: 'Previdência',
  CASH: 'Caixa',
  CRYPTO: 'Cripto',
}

function classLabel(v: unknown): string {
  const s = str(v)
  return s ? (CLASS_LABEL[s] ?? s) : ''
}

const ROLE_LABEL: Record<string, string> = {
  sysadmin: 'Sysadmin',
  admin: 'Admin',
  member: 'Member',
}

function roleLabel(v: unknown): string {
  const s = str(v)
  return s ? (ROLE_LABEL[s] ?? s) : ''
}

function describeRaw(p: ParsedAudit): AuditDescription {
  const { action, resourceType, resourceId, details } = p
  const d = details

  switch (action) {
    // ───────── Auth
    case 'auth.login':
      return {
        actionLabel: 'Login',
        actionTone: 'auth',
        resourceLabel: 'Sessão',
        summary: d.remember_me ? 'Login com "lembrar de mim".' : 'Login na sessão.',
      }

    // ───────── Users (admin actions)
    case 'user.invited':
      return {
        actionLabel: 'Usuário convidado',
        actionTone: 'user',
        resourceLabel: str(d.invited_email) ?? 'Usuário',
        summary: `Convidou ${str(d.invited_email) ?? 'um usuário'} como ${roleLabel(d.role) || 'member'}.`,
        link: { to: '/admin/users', label: 'Ir para usuários' },
      }
    case 'user.role_changed':
      return {
        actionLabel: 'Role alterada',
        actionTone: 'user',
        resourceLabel: `Usuário ${shortId(resourceId)}`,
        summary: `Mudou role de ${roleLabel(d.from) || '—'} para ${roleLabel(d.to) || '—'}.`,
        link: { to: '/admin/users', label: 'Ir para usuários' },
      }
    case 'user.deactivated':
      return {
        actionLabel: 'Usuário desativado',
        actionTone: 'user',
        resourceLabel: str(d.target_email) ?? `Usuário ${shortId(resourceId)}`,
        summary: `Desativou ${str(d.target_email) ?? 'o usuário'}.`,
        link: { to: '/admin/users', label: 'Ir para usuários' },
      }
    case 'user.name_changed':
      return {
        actionLabel: 'Nome alterado',
        actionTone: 'user',
        resourceLabel: `Usuário ${shortId(resourceId)}`,
        summary: `Mudou nome do usuário para "${str(d.name) ?? ''}".`,
        link: { to: '/admin/users', label: 'Ir para usuários' },
      }

    // ───────── Profile (próprio)
    case 'profile.name_changed':
      return {
        actionLabel: 'Nome alterado',
        actionTone: 'profile',
        resourceLabel: 'Próprio perfil',
        summary: 'Atualizou o próprio nome.',
        link: { to: '/profile', label: 'Abrir perfil' },
      }
    case 'profile.password_changed':
      return {
        actionLabel: 'Senha alterada',
        actionTone: 'profile',
        resourceLabel: 'Próprio perfil',
        summary: 'Atualizou a própria senha.',
        link: { to: '/profile', label: 'Abrir perfil' },
      }

    // ───────── Accounts
    case 'account.created':
      return {
        actionLabel: 'Conta criada',
        actionTone: 'account',
        resourceLabel: str(d.name) ?? 'Conta',
        summary: `Criou conta "${str(d.name) ?? ''}" (${str(d.account_type) ?? '—'}).`,
        link: { to: '/accounts', label: 'Ir para contas' },
      }
    case 'account.updated':
      return {
        actionLabel: 'Conta atualizada',
        actionTone: 'account',
        resourceLabel: str(d.name) ?? 'Conta',
        summary: `Atualizou conta "${str(d.name) ?? ''}".`,
        link: { to: '/accounts', label: 'Ir para contas' },
      }
    case 'account.deactivated':
      return {
        actionLabel: 'Conta desativada',
        actionTone: 'account',
        resourceLabel: str(d.name) ?? 'Conta',
        summary: `Desativou conta "${str(d.name) ?? ''}".`,
        link: { to: '/accounts', label: 'Ir para contas' },
      }

    // ───────── Financial Institutions
    case 'financial_institution.created':
      return {
        actionLabel: 'Custodiante criado',
        actionTone: 'fi',
        resourceLabel: str(d.short_name) ?? 'Custodiante',
        summary: `Criou custodiante "${str(d.short_name) ?? ''}".`,
        link: { to: '/sysadmin/financial-institutions', label: 'Ir para custodiantes' },
      }
    case 'financial_institution.updated':
      return {
        actionLabel: 'Custodiante atualizado',
        actionTone: 'fi',
        resourceLabel: str(d.short_name) ?? 'Custodiante',
        summary: `Atualizou custodiante "${str(d.short_name) ?? ''}".`,
        link: { to: '/sysadmin/financial-institutions', label: 'Ir para custodiantes' },
      }
    case 'financial_institution.deactivated':
      return {
        actionLabel: 'Custodiante desativado',
        actionTone: 'fi',
        resourceLabel: str(d.short_name) ?? 'Custodiante',
        summary: `Desativou custodiante "${str(d.short_name) ?? ''}".`,
        link: { to: '/sysadmin/financial-institutions', label: 'Ir para custodiantes' },
      }

    // ───────── Assets
    case 'asset.created':
      return {
        actionLabel: 'Ativo criado',
        actionTone: 'asset',
        resourceLabel: str(d.name) ?? 'Ativo',
        summary: `Criou ativo "${str(d.name) ?? ''}"${classLabel(d.asset_class) ? ` · ${classLabel(d.asset_class)}` : ''}.`,
        link: resourceId ? { to: `/assets/${resourceId}`, label: 'Abrir ativo' } : undefined,
      }
    case 'asset.updated':
      return {
        actionLabel: 'Ativo atualizado',
        actionTone: 'asset',
        resourceLabel: str(d.name) ?? 'Ativo',
        summary: `Atualizou ativo "${str(d.name) ?? ''}"${classLabel(d.asset_class) ? ` · ${classLabel(d.asset_class)}` : ''}.`,
        link: resourceId ? { to: `/assets/${resourceId}`, label: 'Abrir ativo' } : undefined,
      }

    // ───────── Prices
    case 'price.update.manual': {
      const label = str(d.ticker) ?? str(d.name) ?? 'Ativo'
      const oldP = fmtNumber(d.old_price, 4)
      const newP = fmtNumber(d.new_price, 4)
      const src = str(d.price_source) ? ` · ${str(d.price_source)}` : ''
      return {
        actionLabel: 'Preço editado',
        actionTone: 'price',
        resourceLabel: label,
        summary: `Editou preço de ${label}: ${oldP} → ${newP}${src}.`,
        link: resourceId ? { to: `/assets/${resourceId}`, label: 'Abrir ativo' } : undefined,
      }
    }
    case 'price.refresh.cron': {
      const label = str(d.ticker) ?? str(d.name) ?? 'Ativo'
      const oldP = fmtNumber(d.old_price, 4)
      const newP = fmtNumber(d.new_price, 4)
      const src = str(d.source) ? ` · ${str(d.source)}` : ''
      return {
        actionLabel: 'Preço atualizado (auto)',
        actionTone: 'price',
        resourceLabel: label,
        summary: `Cron atualizou preço de ${label}: ${oldP} → ${newP}${src}.`,
        link: resourceId ? { to: `/assets/${resourceId}`, label: 'Abrir ativo' } : undefined,
      }
    }

    // ───────── Asset movements
    case 'asset_movement.created': {
      const assetLabel = str(d.asset_ticker) ?? str(d.asset_name) ?? '—'
      return {
        actionLabel: 'Lançamento criado',
        actionTone: 'movement',
        resourceLabel: `${str(d.type) ?? 'Lançamento'} · ${assetLabel} · ${str(d.event_date) ?? '—'}`,
        summary: `Criou lançamento ${str(d.type) ?? '—'} de ${assetLabel} em ${str(d.event_date) ?? '—'}.`,
        link: str(d.asset_id) ? { to: `/assets/${str(d.asset_id)}`, label: 'Abrir ativo' } : undefined,
      }
    }
    case 'asset_movement.updated': {
      const assetLabel = str(d.asset_ticker) ?? str(d.asset_name) ?? '—'
      return {
        actionLabel: 'Lançamento atualizado',
        actionTone: 'movement',
        resourceLabel: `${str(d.type) ?? 'Lançamento'} · ${assetLabel} · ${str(d.event_date) ?? '—'}`,
        summary: `Atualizou lançamento ${str(d.type) ?? '—'} de ${assetLabel} em ${str(d.event_date) ?? '—'}.`,
        link: str(d.asset_id) ? { to: `/assets/${str(d.asset_id)}`, label: 'Abrir ativo' } : undefined,
      }
    }

    // ───────── Distributions
    case 'distribution.created': {
      const assetLabel = str(d.asset_ticker) ?? str(d.asset_name) ?? '—'
      return {
        actionLabel: 'Provento criado',
        actionTone: 'distribution',
        resourceLabel: `${str(d.type) ?? 'Provento'} · ${assetLabel} · ${str(d.event_date) ?? '—'}`,
        summary: `Registrou provento ${str(d.type) ?? '—'} de ${assetLabel} em ${str(d.event_date) ?? '—'}.`,
        link: str(d.asset_id) ? { to: `/assets/${str(d.asset_id)}`, label: 'Abrir ativo' } : undefined,
      }
    }
    case 'distribution.updated': {
      const assetLabel = str(d.asset_ticker) ?? str(d.asset_name) ?? '—'
      return {
        actionLabel: 'Provento atualizado',
        actionTone: 'distribution',
        resourceLabel: `${str(d.type) ?? 'Provento'} · ${assetLabel} · ${str(d.event_date) ?? '—'}`,
        summary: `Atualizou provento ${str(d.type) ?? '—'} de ${assetLabel} em ${str(d.event_date) ?? '—'}.`,
        link: str(d.asset_id) ? { to: `/assets/${str(d.asset_id)}`, label: 'Abrir ativo' } : undefined,
      }
    }

    // ───────── Attachments
    case 'attachment.uploaded':
      return {
        actionLabel: 'Anexo enviado',
        actionTone: 'attachment',
        resourceLabel: str(d.filename) ?? 'Anexo',
        summary: `Enviou "${str(d.filename) ?? '—'}" (${fmtBytes(d.size_bytes)}) → ${str(d.source_type) ?? '—'}.`,
      }
    case 'attachment.deleted':
      return {
        actionLabel: 'Anexo deletado',
        actionTone: 'attachment',
        resourceLabel: str(d.filename) ?? 'Anexo',
        summary: `Removeu "${str(d.filename) ?? '—'}" (${fmtBytes(d.size_bytes)}).`,
      }

    // ───────── Snapshots
    case 'snapshot.confirm': {
      const ym = ymOf(d.period_end_date)
      return {
        actionLabel: 'Snapshot fechado',
        actionTone: 'snapshot',
        resourceLabel: ym ? `Snapshot ${ym}` : 'Snapshot',
        summary: `Fechou snapshot ${ym ?? '—'} — total ${fmtBRL(d.total_value_brl)}.`,
        link: ym ? { to: `/snapshots/${ym}`, label: 'Abrir snapshot' } : undefined,
      }
    }
    case 'snapshot.reopen': {
      const ym = ymOf(d.period_end_date)
      return {
        actionLabel: 'Snapshot reaberto',
        actionTone: 'snapshot',
        resourceLabel: ym ? `Snapshot ${ym}` : 'Snapshot',
        summary: `Reabriu ${ym ?? 'snapshot'}: ${str(d.reason) ?? '—'} (+${num(d.items_added) ?? 0} itens, +${num(d.pendencies_recreated) ?? 0} pendências).`,
        link: ym ? { to: `/snapshots/${ym}`, label: 'Abrir snapshot' } : undefined,
      }
    }
    case 'snapshot.sync_items': {
      const ym = ymOf(d.period_end_date)
      return {
        actionLabel: 'Snapshot sincronizado',
        actionTone: 'snapshot',
        resourceLabel: ym ? `Snapshot ${ym}` : 'Snapshot',
        summary: `Sincronizou ${ym ?? 'snapshot'}: +${num(d.items_added) ?? 0} itens, +${num(d.pendencies_added) ?? 0} pendências.`,
        link: ym ? { to: `/snapshots/${ym}`, label: 'Abrir snapshot' } : undefined,
      }
    }
    case 'snapshot.auto_monthly': {
      const ym = ymOf(d.period_end_date)
      return {
        actionLabel: 'Snapshot mensal (auto)',
        actionTone: 'snapshot',
        resourceLabel: ym ? `Snapshot ${ym}` : 'Snapshot',
        summary: `Job criou snapshot ${ym ?? '—'} — status ${str(d.status) ?? '—'} (${num(d.items_count) ?? 0} itens, ${num(d.pendencies_count) ?? 0} pendências).`,
        link: ym ? { to: `/snapshots/${ym}`, label: 'Abrir snapshot' } : undefined,
      }
    }
    case 'snapshot.item.add':
      return {
        actionLabel: 'Item adicionado',
        actionTone: 'snapshot',
        resourceLabel: str(d.asset_name) ?? 'Item',
        summary: `Adicionou ${str(d.asset_name) ?? 'item'}${classLabel(d.asset_class) ? ` (${classLabel(d.asset_class)})` : ''} ao snapshot.`,
        link: str(d.asset_id) ? { to: `/assets/${str(d.asset_id)}`, label: 'Abrir ativo' } : undefined,
      }
    case 'snapshot.item.edit': {
      const stored = num(d.stored_unit_price) ?? num(d.input_price)
      const mode = str(d.effective_mode)
      const mv = num(d.market_value_brl)
      const valueMsg = mode === 'VALUE' && mv != null
        ? ` para ${fmtBRL(mv)}`
        : stored != null
          ? ` para ${fmtNumber(stored, 4)}`
          : ''
      const modeMsg = mode ? ` (modo ${mode === 'VALUE' ? 'valor' : 'unitário'})` : ''
      return {
        actionLabel: 'Item editado',
        actionTone: 'snapshot',
        resourceLabel: str(d.asset_name) ?? 'Item',
        summary: `Editou ${str(d.asset_name) ?? 'item'}${valueMsg}${modeMsg}.`,
        link: str(d.asset_id) ? { to: `/assets/${str(d.asset_id)}`, label: 'Abrir ativo' } : undefined,
      }
    }
    case 'snapshot.item.delete':
      return {
        actionLabel: 'Item removido',
        actionTone: 'snapshot',
        resourceLabel: str(d.asset_name) ?? 'Item',
        summary: `Removeu ${str(d.asset_name) ?? 'item'} do snapshot (era ${fmtBRL(d.deleted_market_value_brl)}).`,
        link: str(d.asset_id) ? { to: `/assets/${str(d.asset_id)}`, label: 'Abrir ativo' } : undefined,
      }
    case 'snapshot.item.recompute': {
      const before = (d.before ?? {}) as Record<string, unknown>
      const after = (d.after ?? {}) as Record<string, unknown>
      const bp = num(before.unit_price)
      const ap = num(after.unit_price)
      const priceMsg = bp != null && ap != null
        ? `: ${fmtNumber(bp, 4)} → ${fmtNumber(ap, 4)}`
        : ''
      return {
        actionLabel: 'Item recalculado',
        actionTone: 'snapshot',
        resourceLabel: str(d.asset_name) ?? 'Item',
        summary: `Recalculou ${str(d.asset_name) ?? 'item'} por ${str(d.trigger_event_type) ?? 'evento'}${priceMsg}${d.auto_reopened ? ' (snapshot reaberto)' : ''}.`,
        link: str(d.asset_id) ? { to: `/assets/${str(d.asset_id)}`, label: 'Abrir ativo' } : undefined,
      }
    }
    case 'snapshot.recompute.skipped': {
      const ym = ymOf(d.period_end_date)
      return {
        actionLabel: 'Recálculo pulado',
        actionTone: 'snapshot',
        resourceLabel: str(d.asset_name) ?? 'Item',
        summary: `Pulou recálculo de ${str(d.asset_name) ?? 'item'} em ${ym ?? '—'}: ${str(d.reason) ?? '—'}.`,
        link: ym ? { to: `/snapshots/${ym}`, label: 'Abrir snapshot' } : undefined,
      }
    }

    // ───────── Pendencies
    case 'snapshot.pendency.resolve':
      return {
        actionLabel: 'Pendência resolvida',
        actionTone: 'pendency',
        resourceLabel: `Pendência · ${str(d.reason) ?? '—'}`,
        summary: `Resolveu pendência (${str(d.reason) ?? '—'}) com preço ${fmtNumber(d.new_price, 4)}.`,
        link: str(d.asset_id) ? { to: `/assets/${str(d.asset_id)}`, label: 'Abrir ativo' } : undefined,
      }
    case 'snapshot.pendency.retry_api':
      return {
        actionLabel: 'Retry API',
        actionTone: 'pendency',
        resourceLabel: str(d.ticker) ?? 'Pendência',
        summary: str(d.error)
          ? `Retry de ${str(d.ticker) ?? '—'} falhou: ${str(d.error)}.`
          : `Retry de ${str(d.ticker) ?? '—'}: ${fmtNumber(d.old_price, 4)} → ${fmtNumber(d.new_price, 4)} (${str(d.status) ?? '—'}).`,
        link: str(d.asset_id) ? { to: `/assets/${str(d.asset_id)}`, label: 'Abrir ativo' } : undefined,
      }

    // ───────── Extractions
    case 'extraction.created':
      return {
        actionLabel: 'Extração criada',
        actionTone: 'extraction',
        resourceLabel: str(d.source_hint) ?? 'Extração',
        summary: `Iniciou extração${str(d.source_hint) ? ` (${str(d.source_hint)})` : ''}.`,
      }
    case 'extraction.confirmed': {
      const applied = num(d.applied) ?? 0
      const skipped = num(d.skipped) ?? 0
      const errors = num(d.errors) ?? 0
      const cost = num(d.cost_usd)
      const costMsg = cost != null ? ` · USD ${cost.toFixed(4)}` : ''
      return {
        actionLabel: 'Extração aplicada',
        actionTone: 'extraction',
        resourceLabel: str(d.institution_short_name) ?? 'Extração',
        summary: `Aplicou ${applied} item(ns), ${skipped} pulado(s), ${errors} erro(s)${costMsg}.`,
      }
    }
    case 'extraction.rejected':
      return {
        actionLabel: 'Extração rejeitada',
        actionTone: 'extraction',
        resourceLabel: 'Extração',
        summary: `Rejeitou extração: ${str(d.reason) ?? '—'}.`,
      }

    // ───────── Integration credentials
    case 'integration_credential.created':
      return {
        actionLabel: 'Credencial criada',
        actionTone: 'integration',
        resourceLabel: `${str(d.provider) ?? '—'} · ${str(d.key_name) ?? ''}`,
        summary: `Adicionou credencial de ${str(d.provider) ?? '—'} (${str(d.key_name) ?? '—'}).`,
        link: { to: '/sysadmin/integrations', label: 'Abrir integrações' },
      }
  }

  // ───────── api.{method}.{status} (middleware)
  if (action.startsWith('api.')) {
    const method = str(d.method) ?? action.split('.')[1] ?? ''
    const status = num(d.status) ?? Number(action.split('.')[2]) ?? 0
    const path = str(d.path) ?? ''
    return {
      actionLabel: `API ${method} ${status}`,
      actionTone: 'api',
      resourceLabel: path || 'API',
      summary: path ? `${method} ${path} → ${status}.` : `${action}`,
    }
  }

  // ───────── fallback
  const r = resourceType ?? '—'
  const id = shortId(resourceId)
  return {
    actionLabel: action,
    actionTone: 'generic',
    resourceLabel: id ? `${r} · ${id}` : r,
    summary: 'Ação registrada sem descrição específica. Veja os detalhes abaixo.',
  }
}

export function describeAudit(log: AuditLogOut): AuditDescription {
  return describeRaw({
    action: log.action,
    resourceType: log.resource_type,
    resourceId: log.resource_id,
    details: parseDetails(log.details),
  })
}

export function toneClasses(tone: AuditTone): string {
  switch (tone) {
    case 'auth':
      return 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400'
    case 'user':
      return 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400'
    case 'profile':
      return 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400'
    case 'account':
      return 'bg-teal-100 text-teal-700 dark:bg-teal-900/30 dark:text-teal-400'
    case 'fi':
      return 'bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400'
    case 'asset':
      return 'bg-indigo-100 text-indigo-700 dark:bg-indigo-900/30 dark:text-indigo-400'
    case 'price':
      return 'bg-rose-100 text-rose-700 dark:bg-rose-900/30 dark:text-rose-400'
    case 'movement':
      return 'bg-sky-100 text-sky-700 dark:bg-sky-900/30 dark:text-sky-400'
    case 'distribution':
      return 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400'
    case 'attachment':
      return 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300'
    case 'snapshot':
      return 'bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-400'
    case 'pendency':
      return 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400'
    case 'extraction':
      return 'bg-pink-100 text-pink-700 dark:bg-pink-900/30 dark:text-pink-400'
    case 'integration':
      return 'bg-violet-100 text-violet-700 dark:bg-violet-900/30 dark:text-violet-400'
    case 'api':
    case 'generic':
    default:
      return 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400'
  }
}

export interface ActionFilterGroup {
  label: string
  actions: { value: string; label: string }[]
}

/** Options for the action filter dropdown, grouped by domain. */
export const ACTION_FILTER_GROUPS: ActionFilterGroup[] = [
  {
    label: 'Snapshot',
    actions: [
      { value: 'snapshot.confirm', label: 'Snapshot fechado' },
      { value: 'snapshot.reopen', label: 'Snapshot reaberto' },
      { value: 'snapshot.sync_items', label: 'Snapshot sincronizado' },
      { value: 'snapshot.auto_monthly', label: 'Snapshot mensal (auto)' },
      { value: 'snapshot.item.add', label: 'Item adicionado' },
      { value: 'snapshot.item.edit', label: 'Item editado' },
      { value: 'snapshot.item.delete', label: 'Item removido' },
      { value: 'snapshot.item.recompute', label: 'Item recalculado' },
      { value: 'snapshot.recompute.skipped', label: 'Recálculo pulado' },
      { value: 'snapshot.pendency.resolve', label: 'Pendência resolvida' },
      { value: 'snapshot.pendency.retry_api', label: 'Retry API' },
    ],
  },
  {
    label: 'Ativos & preços',
    actions: [
      { value: 'asset.created', label: 'Ativo criado' },
      { value: 'asset.updated', label: 'Ativo atualizado' },
      { value: 'price.update.manual', label: 'Preço editado' },
      { value: 'price.refresh.cron', label: 'Preço atualizado (auto)' },
      { value: 'asset_movement.created', label: 'Lançamento criado' },
      { value: 'asset_movement.updated', label: 'Lançamento atualizado' },
      { value: 'distribution.created', label: 'Provento criado' },
      { value: 'distribution.updated', label: 'Provento atualizado' },
    ],
  },
  {
    label: 'Anexos & extração',
    actions: [
      { value: 'attachment.uploaded', label: 'Anexo enviado' },
      { value: 'attachment.deleted', label: 'Anexo deletado' },
      { value: 'extraction.created', label: 'Extração criada' },
      { value: 'extraction.confirmed', label: 'Extração aplicada' },
      { value: 'extraction.rejected', label: 'Extração rejeitada' },
    ],
  },
  {
    label: 'Workspace',
    actions: [
      { value: 'account.created', label: 'Conta criada' },
      { value: 'account.updated', label: 'Conta atualizada' },
      { value: 'account.deactivated', label: 'Conta desativada' },
      { value: 'user.invited', label: 'Usuário convidado' },
      { value: 'user.role_changed', label: 'Role alterada' },
      { value: 'user.deactivated', label: 'Usuário desativado' },
      { value: 'user.name_changed', label: 'Nome alterado' },
      { value: 'profile.name_changed', label: 'Nome próprio alterado' },
      { value: 'profile.password_changed', label: 'Senha alterada' },
      { value: 'auth.login', label: 'Login' },
    ],
  },
  {
    label: 'Sysadmin',
    actions: [
      { value: 'financial_institution.created', label: 'Custodiante criado' },
      { value: 'financial_institution.updated', label: 'Custodiante atualizado' },
      { value: 'financial_institution.deactivated', label: 'Custodiante desativado' },
      { value: 'integration_credential.created', label: 'Credencial criada' },
    ],
  },
]
