import { useMemo, useState } from 'react'
import { ChevronRight, ChevronDown } from 'lucide-react'
import { type AssetOut, type FinancialInstitutionOut, type PositionOut } from '../lib/api'
import { KLASS, collapsedOf, type CollapsedClassCode } from '../lib/tokens'
import { ClassBadge, FILogo } from './ui'

interface Props {
  assets: AssetOut[]
  positions: Map<string, PositionOut | null>
  institutions: FinancialInstitutionOut[]
  grouping: 'none' | 'klass' | 'fi'
  showWorkspaceColumn?: boolean
  onRowClick: (asset: AssetOut) => void
}

interface Group {
  key: string
  label: string
  color?: string
  items: AssetOut[]
}

function fmtNum(n: number | null | undefined, digits = 2) {
  if (n == null) return '—'
  return n.toLocaleString('pt-BR', { maximumFractionDigits: digits, minimumFractionDigits: digits })
}

function fmtMoney(n: number | null | undefined, currency: string, opts: { compact?: boolean } = {}) {
  if (n == null) return '—'
  if (opts.compact && Math.abs(n) >= 1000) {
    return n.toLocaleString('pt-BR', { style: 'currency', currency, notation: 'compact', maximumFractionDigits: 1 })
  }
  return n.toLocaleString('pt-BR', { style: 'currency', currency })
}

export default function AssetTable({
  assets, positions, institutions, grouping, showWorkspaceColumn, onRowClick,
}: Props) {
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
    return (
      <Card>
        <Table
          assets={assets}
          positions={positions}
          fiById={fiById}
          showWorkspaceColumn={showWorkspaceColumn}
          onRowClick={onRowClick}
        />
      </Card>
    )
  }

  return (
    <div className="space-y-4">
      {groups.map(g => (
        <GroupCard
          key={g.key}
          group={g}
          positions={positions}
          fiById={fiById}
          showWorkspaceColumn={showWorkspaceColumn}
          onRowClick={onRowClick}
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
  group, positions, fiById, showWorkspaceColumn, onRowClick,
}: {
  group: Group
  positions: Map<string, PositionOut | null>
  fiById: Map<string, FinancialInstitutionOut>
  showWorkspaceColumn?: boolean
  onRowClick: (a: AssetOut) => void
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
          onRowClick={onRowClick}
        />
      )}
    </div>
  )
}

function Table({
  assets, positions, fiById, showWorkspaceColumn, onRowClick,
}: {
  assets: AssetOut[]
  positions: Map<string, PositionOut | null>
  fiById: Map<string, FinancialInstitutionOut>
  showWorkspaceColumn?: boolean
  onRowClick: (a: AssetOut) => void
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
            <th className="text-left font-medium px-2 py-2">Ativo</th>
            <th className="text-left font-medium px-2 py-2">Classe</th>
            <th className="text-left font-medium px-2 py-2">Custodiante</th>
            <th className="text-right font-medium px-2 py-2">Qtd</th>
            <th className="text-right font-medium px-2 py-2">Preço médio</th>
            <th className="text-right font-medium px-2 py-2" title="Depende do spec 09 (current_price)">Atual</th>
            <th className="text-right font-medium px-2 py-2" title="Depende do spec 09">Valor</th>
            <th className="text-right font-medium px-2 py-2" title="Depende do spec 09">Variação</th>
            <th className="text-right font-medium px-2 py-2" title="Depende do spec 09">Rentab.</th>
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
            />
          ))}
        </tbody>
      </table>
    </div>
  )
}

function Row({
  asset, position, fi, showWorkspaceColumn, onClick,
}: {
  asset: AssetOut
  position: PositionOut | null
  fi: FinancialInstitutionOut | null
  showWorkspaceColumn?: boolean
  onClick: () => void
}) {
  const klass = collapsedOf(asset.asset_class)
  const color = KLASS[klass].color
  const inactive = !asset.is_active
  const qty = position?.quantity_held ?? null
  const avg = position?.average_cost ?? null

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
            <div className={`font-mono font-medium text-gray-900 dark:text-gray-100 ${inactive ? 'line-through' : ''}`}>
              {asset.ticker || asset.name}
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
        {qty == null ? <span className="text-gray-300 dark:text-gray-700">…</span> : fmtNum(qty, qty < 100 ? 2 : 0)}
      </td>
      <td className="px-2 text-right tnum money text-gray-500 dark:text-gray-400">
        {avg == null ? <span className="text-gray-300 dark:text-gray-700">…</span> : fmtMoney(avg, asset.currency)}
      </td>
      <td className="px-2 text-right text-gray-300 dark:text-gray-700">—</td>
      <td className="px-2 text-right text-gray-300 dark:text-gray-700">—</td>
      <td className="px-2 text-right text-gray-300 dark:text-gray-700">—</td>
      <td className="px-2 text-right text-gray-300 dark:text-gray-700">—</td>
      <td className="px-2 text-gray-500">
        <ChevronRight className="w-4 h-4" />
      </td>
    </tr>
  )
}
