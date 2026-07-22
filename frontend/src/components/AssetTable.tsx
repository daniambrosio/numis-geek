import { useMemo, useState } from 'react'
import { ChevronRight, ChevronDown, ChevronUp, ChevronsUpDown } from 'lucide-react'
import { type AssetOut, type FinancialInstitutionOut, type PositionOut } from '../lib/api'
import { KLASS, collapsedOf, type CollapsedClassCode } from '../lib/tokens'
import { fmtMoney as fmtMoneyBase } from '../lib/money'
import { ClassBadge, FILogo } from './ui'
import PriceCell from './PriceCell'

interface Props {
  assets: AssetOut[]
  positions: Map<string, PositionOut | null>
  institutions: FinancialInstitutionOut[]
  grouping: 'none' | 'klass' | 'fi'
  showWorkspaceColumn?: boolean
  onRowClick: (asset: AssetOut) => void
  /** Called when the per-row refresh button updates a single asset.
   * The parent should merge it back into its assets state. */
  onAssetUpdated?: (updated: AssetOut) => void
}

interface Group {
  key: string
  label: string
  color?: string
  items: AssetOut[]
}

export type SortKey =
  | 'ticker' | 'klass' | 'fi' | 'qty' | 'avg' | 'current_price'
  | 'current_value' | 'variation' | 'rentabilidade'
  | 'dividend_yield' | 'yield_on_cost' | 'updated'
export type SortDir = 'asc' | 'desc' | null

interface SortState {
  key: SortKey | null
  dir: SortDir
}

function fmtNum(n: number | null | undefined, digits = 2) {
  if (n == null) return '—'
  return n.toLocaleString('pt-BR', { maximumFractionDigits: digits, minimumFractionDigits: digits })
}

function fmtMoney(n: number | null | undefined, currency: string, opts: { compact?: boolean } = {}) {
  if (n == null) return '—'
  if (currency === 'BRL' || currency === 'USD') {
    return fmtMoneyBase(n, currency, { compact: opts.compact })
  }
  return n.toLocaleString('pt-BR', { style: 'currency', currency })
}

function fmtPct(n: number | null | undefined) {
  if (n == null) return '—'
  return `${(n * 100).toFixed(2)}%`
}

function sortValue(
  asset: AssetOut,
  position: PositionOut | null,
  fi: FinancialInstitutionOut | null,
  key: SortKey,
): number | string | null {
  switch (key) {
    case 'ticker': return (asset.ticker || asset.name || '').toLowerCase()
    case 'klass': return KLASS[collapsedOf(asset.asset_class)].label.toLowerCase()
    case 'fi': return (fi?.short_name || '').toLowerCase()
    case 'qty': return position?.quantity_held ?? null
    case 'avg': return position?.average_cost ?? null
    case 'current_price': return position?.current_price ?? null
    case 'current_value': return position?.current_value_brl ?? position?.current_value ?? null
    case 'variation': return position?.variation ?? null
    case 'rentabilidade': return position?.rentabilidade ?? null
    case 'dividend_yield': return position?.dividend_yield ?? null
    case 'yield_on_cost': return position?.yield_on_cost ?? null
    case 'updated': return asset.price_updated_at ?? null
  }
}

function sortAssets(
  items: AssetOut[],
  positions: Map<string, PositionOut | null>,
  fiById: Map<string, FinancialInstitutionOut>,
  sort: SortState,
): AssetOut[] {
  if (!sort.key || !sort.dir) return items
  const { key, dir } = sort
  const mult = dir === 'asc' ? 1 : -1
  const decorated = items.map((a, i) => ({
    a, i,
    v: sortValue(a, positions.get(a.id) ?? null, fiById.get(a.financial_institution_id) ?? null, key),
  }))
  decorated.sort((x, y) => {
    // nulls/empties always last, regardless of direction
    const xn = x.v == null || x.v === ''
    const yn = y.v == null || y.v === ''
    if (xn && yn) return x.i - y.i
    if (xn) return 1
    if (yn) return -1
    if (typeof x.v === 'number' && typeof y.v === 'number') {
      return (x.v - y.v) * mult
    }
    return String(x.v).localeCompare(String(y.v), 'pt-BR') * mult
  })
  return decorated.map(d => d.a)
}

function nextSort(current: SortState, key: SortKey): SortState {
  if (current.key !== key) return { key, dir: 'asc' }
  if (current.dir === 'asc') return { key, dir: 'desc' }
  if (current.dir === 'desc') return { key: null, dir: null }
  return { key, dir: 'asc' }
}

export default function AssetTable({
  assets, positions, institutions, grouping, showWorkspaceColumn, onRowClick, onAssetUpdated,
}: Props) {
  const [sort, setSort] = useState<SortState>({ key: null, dir: null })
  const onSort = (key: SortKey) => setSort(prev => nextSort(prev, key))

  const fiById = useMemo(() => {
    const m = new Map<string, FinancialInstitutionOut>()
    for (const fi of institutions) m.set(fi.id, fi)
    return m
  }, [institutions])

  const groups: Group[] = useMemo(() => {
    if (grouping === 'none') {
      return [{ key: 'flat', label: '', items: assets }]
    }
    if (grouping === 'klass') {
      const map = new Map<CollapsedClassCode, AssetOut[]>()
      for (const a of assets) {
        const key = collapsedOf(a.asset_class)
        if (!map.has(key)) map.set(key, [])
        map.get(key)!.push(a)
      }
      return Array.from(map.entries())
        .map(([key, items]) => ({
          key,
          label: KLASS[key].label,
          color: KLASS[key].color,
          items,
        }))
        .sort((a, b) => b.items.length - a.items.length)
    }
    // fi
    const map = new Map<string, AssetOut[]>()
    for (const a of assets) {
      const key = a.financial_institution_id
      if (!map.has(key)) map.set(key, [])
      map.get(key)!.push(a)
    }
    return Array.from(map.entries())
      .map(([key, items]) => ({
        key,
        label: fiById.get(key)?.short_name ?? key.slice(0, 8),
        items,
      }))
      .sort((a, b) => b.items.length - a.items.length)
  }, [assets, grouping, fiById])

  if (grouping === 'none') {
    const sorted = sortAssets(assets, positions, fiById, sort)
    return (
      <Card>
        <Table
          assets={sorted}
          positions={positions}
          fiById={fiById}
          showWorkspaceColumn={showWorkspaceColumn}
          sort={sort}
          onSort={onSort}
          onRowClick={onRowClick}
          onAssetUpdated={onAssetUpdated}
        />
      </Card>
    )
  }

  return (
    <div className="space-y-4">
      {groups.map(g => (
        <GroupCard
          key={g.key}
          group={{ ...g, items: sortAssets(g.items, positions, fiById, sort) }}
          positions={positions}
          fiById={fiById}
          showWorkspaceColumn={showWorkspaceColumn}
          sort={sort}
          onSort={onSort}
          onRowClick={onRowClick}
          onAssetUpdated={onAssetUpdated}
        />
      ))}
    </div>
  )
}

function Card({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-2xl bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 p-3">
      {children}
    </div>
  )
}

function GroupCard({
  group, positions, fiById, showWorkspaceColumn, sort, onSort, onRowClick, onAssetUpdated,
}: {
  group: Group
  positions: Map<string, PositionOut | null>
  fiById: Map<string, FinancialInstitutionOut>
  showWorkspaceColumn?: boolean
  sort: SortState
  onSort: (key: SortKey) => void
  onRowClick: (a: AssetOut) => void
  onAssetUpdated?: (updated: AssetOut) => void
}) {
  const [open, setOpen] = useState(true)
  return (
    <div className="rounded-2xl bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 p-3">
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center gap-2 px-2 py-1.5 mb-2 border-b border-gray-200 dark:border-gray-800 hover:opacity-80"
      >
        <ChevronDown className={`w-3.5 h-3.5 text-gray-500 transition-transform ${open ? '' : '-rotate-90'}`} />
        {group.color && <span className="w-1.5 h-5 rounded-full" style={{ background: group.color }} />}
        <span className="font-semibold text-[13px]">{group.label}</span>
        <span className="text-[10px] text-gray-500 tnum">· {group.items.length}</span>
      </button>
      {open && (
        <Table
          assets={group.items}
          positions={positions}
          fiById={fiById}
          showWorkspaceColumn={showWorkspaceColumn}
          sort={sort}
          onSort={onSort}
          onRowClick={onRowClick}
          onAssetUpdated={onAssetUpdated}
        />
      )}
    </div>
  )
}

function SortHeader({
  colKey, label, align = 'left', title, sort, onSort,
}: {
  colKey: SortKey
  label: string
  align?: 'left' | 'right'
  title?: string
  sort: SortState
  onSort: (k: SortKey) => void
}) {
  const active = sort.key === colKey && sort.dir !== null
  const dir = active ? sort.dir : null
  const justify = align === 'right' ? 'justify-end' : 'justify-start'
  return (
    <th
      className={`text-${align} font-medium px-2 py-2 select-none`}
      title={title}
    >
      <button
        type="button"
        onClick={() => onSort(colKey)}
        className={`inline-flex items-center gap-1 ${justify} w-full hover:text-gray-700 dark:hover:text-gray-200 transition-colors ${
          active ? 'text-indigo-500 dark:text-indigo-400' : ''
        }`}
      >
        <span>{label}</span>
        {dir === 'asc' && <ChevronUp className="w-3 h-3" />}
        {dir === 'desc' && <ChevronDown className="w-3 h-3" />}
        {!dir && <ChevronsUpDown className="w-3 h-3 opacity-30" />}
      </button>
    </th>
  )
}

function Table({
  assets, positions, fiById, showWorkspaceColumn, sort, onSort, onRowClick, onAssetUpdated,
}: {
  assets: AssetOut[]
  positions: Map<string, PositionOut | null>
  fiById: Map<string, FinancialInstitutionOut>
  showWorkspaceColumn?: boolean
  sort: SortState
  onSort: (k: SortKey) => void
  onRowClick: (a: AssetOut) => void
  onAssetUpdated?: (updated: AssetOut) => void
}) {
  if (assets.length === 0) {
    return (
      <div className="py-12 text-center text-sm text-gray-400 dark:text-gray-600">
        Nenhum ativo encontrado.
      </div>
    )
  }
  return (
    <div className="overflow-x-auto -mx-1">
      <table className="w-full text-[12px]">
        <thead>
          <tr className="text-[10px] uppercase tracking-wider text-gray-500">
            {showWorkspaceColumn && <th className="text-left font-medium px-2 py-2">Workspace</th>}
            <SortHeader colKey="ticker" label="Ativo" align="left" sort={sort} onSort={onSort} />
            <SortHeader colKey="klass" label="Classe" align="left" sort={sort} onSort={onSort} />
            <SortHeader colKey="fi" label="Custodiante" align="left" sort={sort} onSort={onSort} />
            <SortHeader colKey="qty" label="Qtd" align="right" sort={sort} onSort={onSort} />
            <SortHeader colKey="avg" label="Preço médio" align="right" sort={sort} onSort={onSort} />
            <SortHeader colKey="current_price" label="Atual" align="right" sort={sort} onSort={onSort} />
            <SortHeader colKey="current_value" label="Valor" align="right" sort={sort} onSort={onSort} />
            <SortHeader colKey="variation" label="Variação" align="right" title="Variação no preço do papel" sort={sort} onSort={onSort} />
            <SortHeader colKey="rentabilidade" label="Rentab." align="right" title="Variação + proventos recebidos" sort={sort} onSort={onSort} />
            <SortHeader colKey="dividend_yield" label="DY" align="right" title="Dividend Yield — Σ proventos últimos 12 meses / valor atual" sort={sort} onSort={onSort} />
            <SortHeader colKey="yield_on_cost" label="YoC" align="right" title="Yield on Cost — Σ proventos últimos 12 meses / custo investido" sort={sort} onSort={onSort} />
            <SortHeader colKey="updated" label="Atualizado" align="left" sort={sort} onSort={onSort} />
            <th className="px-2"></th>
          </tr>
        </thead>
        <tbody>
          {assets.map(a => (
            <Row
              key={a.id}
              asset={a}
              position={positions.get(a.id) ?? null}
              fi={fiById.get(a.financial_institution_id) ?? null}
              showWorkspaceColumn={showWorkspaceColumn}
              onClick={() => onRowClick(a)}
              onAssetUpdated={onAssetUpdated}
            />
          ))}
        </tbody>
      </table>
    </div>
  )
}

function Row({
  asset, position, fi, showWorkspaceColumn, onClick, onAssetUpdated,
}: {
  asset: AssetOut
  position: PositionOut | null
  fi: FinancialInstitutionOut | null
  showWorkspaceColumn?: boolean
  onClick: () => void
  onAssetUpdated?: (updated: AssetOut) => void
}) {
  const klass = collapsedOf(asset.asset_class)
  const color = KLASS[klass].color
  const inactive = !asset.is_active
  const qty = position?.quantity_held ?? null
  const avg = position?.average_cost ?? null
  // Fase 3.3 (2026-07-22): value-mode (FUND/PREV/FGTS/RE/VE/FI/CASH)
  // não tem preço unitário nem qty semânticos (qty=1 sempre; unit_price
  // é VALOR TOTAL). Renderizar Qtd/Atual per-share nesses ativos é
  // ruído — só faz sentido em modo cotado.
  const _COTADO_CLASSES = new Set(['STOCK', 'REIT', 'ETF', 'OPTION', 'CRYPTO'])
  const isValueMode = !_COTADO_CLASSES.has(asset.asset_class)

  return (
    <tr
      onClick={onClick}
      className={`border-t border-gray-100 dark:border-gray-800 hover:bg-gray-50 dark:hover:bg-gray-800/30 transition-colors cursor-pointer ${
        inactive ? 'opacity-60' : ''
      }`}
    >
      {showWorkspaceColumn && (
        <td className="px-2 py-2.5 text-[11px] text-gray-500 dark:text-gray-400 truncate max-w-[160px]">
          {asset.workspace_name ?? asset.workspace_id.slice(0, 8)}
        </td>
      )}
      <td className="px-2 py-2.5">
        <div className="flex items-center gap-2">
          <span className="w-1 h-5 rounded-full shrink-0" style={{ background: color }} />
          <div className="min-w-0">
            <div className={`font-mono font-medium text-gray-900 dark:text-gray-100 flex items-center gap-1.5 ${inactive ? 'line-through' : ''}`}>
              {asset.ticker || asset.name}
              <span className="text-[11px] leading-none" title={asset.country}>
                {asset.country === 'BR' ? '🇧🇷' : asset.country === 'US' ? '🇺🇸' : '🌐'}
              </span>
            </div>
            {asset.ticker && (
              <div className="text-[11px] text-gray-500 dark:text-gray-400 truncate max-w-[260px]">{asset.name}</div>
            )}
          </div>
        </div>
      </td>
      <td className="px-2">
        <ClassBadge klass={klass} size="xs" withDot={false} />
      </td>
      <td className="px-2">
        {fi && (
          <div className="flex items-center gap-1.5">
            <FILogo slug={fi.logo_slug} shortName={fi.short_name} size="sm" />
            <span className="text-[11px] text-gray-500 dark:text-gray-400">{fi.short_name}</span>
          </div>
        )}
      </td>
      <td className="px-2 text-right tnum text-gray-700 dark:text-gray-300">
        {isValueMode
          ? <span className="text-gray-300 dark:text-gray-700">—</span>
          : (qty == null
              ? <span className="text-gray-300 dark:text-gray-700">…</span>
              : fmtNum(qty, qty < 100 ? 2 : 0))}
      </td>
      <td className="px-2 text-right tnum money text-gray-500 dark:text-gray-400">
        {isValueMode
          ? <span className="text-gray-300 dark:text-gray-700">—</span>
          : (avg == null
              ? <span className="text-gray-300 dark:text-gray-700">…</span>
              : fmtMoney(avg, asset.currency))}
      </td>
      <td className="px-2 text-right tnum money text-gray-700 dark:text-gray-300">
        {isValueMode || position?.current_price == null
          ? <span className="text-gray-300 dark:text-gray-700">—</span>
          : fmtMoney(position.current_price, asset.currency)}
      </td>
      <td className="px-2 text-right tnum money font-medium text-gray-900 dark:text-white">
        {position?.current_value == null
          ? <span className="text-gray-300 dark:text-gray-700">—</span>
          : fmtMoney(position.current_value, asset.currency, { compact: true })}
      </td>
      <td className={`px-2 text-right tnum font-medium ${
        position?.variation == null ? 'text-gray-300 dark:text-gray-700'
        : position.variation >= 0 ? 'text-emerald-500 dark:text-emerald-400'
        : 'text-red-500 dark:text-red-400'
      }`}>
        {position?.variation == null
          ? '—'
          : `${position.variation >= 0 ? '+' : ''}${(position.variation * 100).toFixed(2)}%`}
      </td>
      <td className={`px-2 text-right tnum font-medium ${
        position?.rentabilidade == null ? 'text-gray-300 dark:text-gray-700'
        : position.rentabilidade >= 0 ? 'text-emerald-500 dark:text-emerald-400'
        : 'text-red-500 dark:text-red-400'
      }`}>
        {position?.rentabilidade == null
          ? '—'
          : `${position.rentabilidade >= 0 ? '+' : ''}${(position.rentabilidade * 100).toFixed(2)}%`}
      </td>
      <td className={`px-2 text-right tnum font-medium ${
        position?.dividend_yield == null
          ? 'text-gray-300 dark:text-gray-700'
          : 'text-gray-700 dark:text-gray-300'
      }`}>
        {fmtPct(position?.dividend_yield)}
      </td>
      <td className={`px-2 text-right tnum font-medium ${
        position?.yield_on_cost == null
          ? 'text-gray-300 dark:text-gray-700'
          : 'text-gray-700 dark:text-gray-300'
      }`}>
        {fmtPct(position?.yield_on_cost)}
      </td>
      <td className="px-2">
        <PriceCell asset={asset} onUpdated={onAssetUpdated} />
      </td>
      <td className="px-2 text-gray-500">
        <ChevronRight className="w-4 h-4" />
      </td>
    </tr>
  )
}
