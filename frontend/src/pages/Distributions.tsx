import { Fragment, useEffect, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Plus } from 'lucide-react'
import {
  api,
  DISTRIBUTION_TYPE_LABELS,
  type AssetOut,
  type DistributionOut,
  type DistributionRequest,
  type DistributionType,
  type FinancialInstitutionOut,
  type UserOut,
} from '../lib/api'
import AppLayout from '../components/AppLayout'
import DistributionComposer from '../components/DistributionComposer'
import DistributionDetailPanel from '../components/DistributionDetailPanel'
import {
  Card, FilterGroup, GroupingToggle, MultiChips, PageHeader, SearchInput,
} from '../components/ui'
import { KLASS, collapsedOf } from '../lib/tokens'

const TYPE_ORDER: DistributionType[] = ['DIVIDEND', 'INTEREST', 'JCP', 'SECURITIES_LENDING']

const TYPE_COLOR: Record<DistributionType, string> = {
  DIVIDEND: '#22c55e',
  INTEREST: '#3b82f6',
  JCP: '#f59e0b',
  SECURITIES_LENDING: '#8b5cf6',
}

const TYPE_OPTS = TYPE_ORDER.map(id => ({
  id,
  label: DISTRIBUTION_TYPE_LABELS[id],
  color: TYPE_COLOR[id],
}))

const VIEW_OPTS = [
  { id: 'month', label: 'Por mês' },
  { id: 'asset', label: 'Por ativo' },
]

const MONTH_NAMES = [
  'Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho',
  'Julho', 'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro',
]

function fmtBRL(n: number, opts: { sign?: boolean; compact?: boolean } = {}) {
  const v = opts.sign ? Math.abs(n) : n
  const sign = opts.sign && n > 0 ? '+ ' : opts.sign && n < 0 ? '− ' : ''
  if (opts.compact && Math.abs(v) >= 1000) {
    return sign + v.toLocaleString('pt-BR', {
      style: 'currency', currency: 'BRL',
      notation: 'compact', maximumFractionDigits: 1,
    })
  }
  return sign + v.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })
}

function fmtMoney(n: number, ccy: string, opts: { sign?: boolean } = {}) {
  const v = opts.sign ? Math.abs(n) : n
  const sign = opts.sign && n > 0 ? '+ ' : opts.sign && n < 0 ? '− ' : ''
  return sign + v.toLocaleString('pt-BR', { style: 'currency', currency: ccy })
}

function fmtPct(n: number, digits = 0) {
  return (n * 100).toFixed(digits) + '%'
}

function fmtDate(iso: string) {
  return new Intl.DateTimeFormat('pt-BR').format(new Date(iso + 'T00:00:00'))
}

export default function Distributions() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const [me, setMe] = useState<UserOut | null>(null)
  const [items, setItems] = useState<DistributionOut[]>([])
  const [assets, setAssets] = useState<AssetOut[]>([])
  const [institutions, setInstitutions] = useState<FinancialInstitutionOut[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')

  // Composer + detail panel state
  const [composerOpen, setComposerOpen] = useState(false)
  const [editing, setEditing] = useState<DistributionOut | undefined>(undefined)
  const [selected, setSelected] = useState<DistributionOut | null>(null)
  const [confirmDeactivate, setConfirmDeactivate] = useState<DistributionOut | null>(null)

  // Filters
  const [search, setSearch] = useState('')
  const [typesSel, setTypesSel] = useState<string[]>([])
  const [view, setView] = useState<'month' | 'asset'>('month')

  useEffect(() => {
    api.me().then(setMe).catch(() => navigate('/login'))
  }, [navigate])

  useEffect(() => {
    if (searchParams.get('compose') === 'distribution') {
      setEditing(undefined)
      setComposerOpen(true)
      const next = new URLSearchParams(searchParams)
      next.delete('compose')
      setSearchParams(next, { replace: true })
    }
  }, [searchParams, setSearchParams])

  useEffect(() => {
    if (!me) return
    setLoading(true)
    setLoadError('')
    const params = {
      type: typesSel.length === 1 ? (typesSel[0] as DistributionType) : undefined,
      page_size: 200,
    }
    Promise.all([
      api.listDistributions({ ...params, page: 1 }),
      api.listAssets({ include_inactive: true }),
      api.listFinancialInstitutions(),
    ])
      .then(async ([firstPage, as, fis]) => {
        setAssets(as)
        setInstitutions(fis)
        const totalPages = Math.ceil(firstPage.total / firstPage.page_size)
        if (totalPages <= 1) {
          setItems(firstPage.items)
          return
        }
        const rest = await Promise.all(
          Array.from({ length: totalPages - 1 }, (_, i) =>
            api.listDistributions({ ...params, page: i + 2 }),
          ),
        )
        setItems(firstPage.items.concat(...rest.map(p => p.items)))
      })
      .catch(err => setLoadError(err instanceof Error ? err.message : 'Erro ao carregar.'))
      .finally(() => setLoading(false))
  }, [me, typesSel])

  const assetById = useMemo(() => {
    const m = new Map<string, AssetOut>()
    for (const a of assets) m.set(a.id, a)
    return m
  }, [assets])
  const fiById = useMemo(() => {
    const m = new Map<string, FinancialInstitutionOut>()
    for (const fi of institutions) m.set(fi.id, fi)
    return m
  }, [institutions])

  // Client-side filters (search; multi-type when >1 selected).
  const filtered = useMemo(() => {
    let xs = items
    if (typesSel.length > 1) xs = xs.filter(x => typesSel.includes(x.type))
    if (search.trim()) {
      const q = search.trim().toLowerCase()
      xs = xs.filter(d => {
        const a = d.asset_id ? assetById.get(d.asset_id) : null
        const fi = fiById.get(d.financial_institution_id)
        return (a?.ticker || '').toLowerCase().includes(q)
          || (a?.name || '').toLowerCase().includes(q)
          || (fi?.short_name || '').toLowerCase().includes(q)
      })
    }
    return xs
  }, [items, typesSel, search, assetById, fiById])

  const sorted = useMemo(
    () => [...filtered].sort((a, b) => b.event_date.localeCompare(a.event_date)),
    [filtered],
  )

  // Group by Year-Month
  const grouped = useMemo(() => {
    const m = new Map<string, DistributionOut[]>()
    for (const it of sorted) {
      const ym = it.event_date.slice(0, 7)
      if (!m.has(ym)) m.set(ym, [])
      m.get(ym)!.push(it)
    }
    return Array.from(m.entries()).map(([ym, arr]) => ({ ym, items: arr }))
  }, [sorted])

  // Stats
  const stats = useMemo(() => {
    const totalNet = sorted.reduce((s, d) => s + d.net_amount * d.fx_rate, 0)
    const totalGross = sorted.reduce((s, d) => s + d.gross_amount * d.fx_rate, 0)
    const totalTax = sorted.reduce((s, d) => s + (d.tax || 0) * d.fx_rate, 0)
    const byType: Record<string, number> = {}
    for (const d of sorted) {
      byType[d.type] = (byType[d.type] || 0) + d.net_amount * d.fx_rate
    }
    const uniqAssets = new Set(sorted.filter(d => d.asset_id).map(d => d.asset_id!)).size
    return { totalNet, totalGross, totalTax, byType, count: sorted.length, uniqAssets }
  }, [sorted])

  // By-asset aggregation for view=asset
  const assetRows = useMemo(() => {
    type Row = { asset_id: string | null; fi_id: string; total: number; count: number }
    const m = new Map<string, Row>()
    for (const d of sorted) {
      const key = d.asset_id || `__noticker_${d.financial_institution_id}`
      const row = m.get(key)
      if (row) {
        row.total += d.net_amount * d.fx_rate
        row.count += 1
      } else {
        m.set(key, {
          asset_id: d.asset_id,
          fi_id: d.financial_institution_id,
          total: d.net_amount * d.fx_rate,
          count: 1,
        })
      }
    }
    return Array.from(m.values()).sort((a, b) => b.total - a.total)
  }, [sorted])

  async function handleSave(data: DistributionRequest) {
    if (editing) {
      const updated = await api.updateDistribution(editing.id, data)
      setItems(prev => prev.map(d => d.id === updated.id ? updated : d))
      if (selected?.id === updated.id) setSelected(updated)
    } else {
      const created = await api.createDistribution(data)
      setItems(prev => [created, ...prev])
    }
  }

  async function handleDeactivate(d: DistributionOut) {
    await api.deactivateDistribution(d.id)
    setItems(prev => prev.filter(x => x.id !== d.id))
    if (selected?.id === d.id) setSelected(null)
    setConfirmDeactivate(null)
  }

  if (!me) return null

  return (
    <AppLayout user={me}>
      <div className="space-y-6">
        <PageHeader
          title="Proventos"
          count={stats.count}
          countLabel={`distribuições · ${stats.uniqAssets} ativo${stats.uniqAssets === 1 ? '' : 's'}`}
          action={
            <button
              onClick={() => { setEditing(undefined); setComposerOpen(true) }}
              disabled={institutions.length === 0}
              className="h-8 px-3 inline-flex items-center gap-1.5 rounded-lg text-[12px] bg-indigo-500 hover:bg-indigo-400 disabled:opacity-50 text-white transition-colors"
            >
              <Plus className="w-3.5 h-3.5" /> Novo Provento
            </button>
          }
        />

        {/* Totals + by-type */}
        <div className="grid grid-cols-12 gap-4">
          <Card className="col-span-12 lg:col-span-5">
            <div className="text-[10px] font-semibold uppercase tracking-wider text-gray-500 mb-2">
              Total recebido (líquido)
            </div>
            <div className="text-3xl font-semibold tnum money">{fmtBRL(stats.totalNet)}</div>
            <div className="text-[11px] text-gray-500 mt-1">
              Bruto <span className="tnum money text-gray-700 dark:text-gray-300">{fmtBRL(stats.totalGross, { compact: true })}</span>
              {' · '}
              IR retido <span className="tnum money text-amber-600 dark:text-amber-400">{fmtBRL(stats.totalTax, { compact: true })}</span>
            </div>
          </Card>
          <Card className="col-span-12 lg:col-span-7">
            <div className="text-[10px] font-semibold uppercase tracking-wider text-gray-500 mb-2">
              Por tipo
            </div>
            <div className="grid grid-cols-4 gap-2">
              {TYPE_OPTS.map(t => {
                const v = stats.byType[t.id] || 0
                return (
                  <div
                    key={t.id}
                    className="px-3 py-2 rounded-lg bg-gray-50 dark:bg-gray-800/40 border border-gray-200 dark:border-gray-800"
                  >
                    <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-gray-500">
                      <span className="w-1.5 h-1.5 rounded-full" style={{ background: t.color }} />
                      {t.label}
                    </div>
                    <div className="mt-1 text-sm font-semibold tnum money">
                      {fmtBRL(v, { compact: true })}
                    </div>
                    <div className="text-[10px] text-gray-500 tnum">
                      {stats.totalNet ? fmtPct(v / stats.totalNet) : '—'}
                    </div>
                  </div>
                )
              })}
            </div>
          </Card>
        </div>

        {/* Filters */}
        <Card padding="p-3" className="space-y-3">
          <div className="flex items-center gap-3 flex-wrap">
            <SearchInput value={search} onChange={setSearch} placeholder="Ativo, ticker, instituição…" />
            <div className="flex-1" />
            <span className="text-[10px] uppercase tracking-wider text-gray-500 font-medium">Visão</span>
            <GroupingToggle
              value={view}
              onChange={v => setView(v as 'month' | 'asset')}
              options={VIEW_OPTS}
            />
          </div>
          <div className="space-y-2 pt-3 border-t border-gray-200 dark:border-gray-800">
            <FilterGroup label="Tipo">
              <MultiChips options={TYPE_OPTS} selected={typesSel} onChange={setTypesSel} />
            </FilterGroup>
          </div>
        </Card>

        {loading && (
          <div className="text-[12px] text-gray-500">Carregando…</div>
        )}
        {loadError && (
          <div className="rounded-lg border border-red-200 dark:border-red-900 bg-red-50 dark:bg-red-900/20 p-4 text-[13px] text-red-700 dark:text-red-300">
            {loadError}
          </div>
        )}

        {/* Body */}
        {!loading && view === 'month' && (
          <Card padding="p-3">
            <div className="overflow-x-auto -mx-1">
              <table className="w-full text-[12px]">
                <thead>
                  <tr className="text-[10px] uppercase tracking-wider text-gray-500">
                    <th className="text-left font-medium px-2 py-2">Data</th>
                    <th className="text-left font-medium px-2 py-2">Tipo</th>
                    <th className="text-left font-medium px-2 py-2">Ativo / IF</th>
                    <th className="text-right font-medium px-2 py-2">Bruto</th>
                    <th className="text-right font-medium px-2 py-2">IR</th>
                    <th className="text-right font-medium px-2 py-2">Líquido</th>
                  </tr>
                </thead>
                <tbody>
                  {grouped.map(g => {
                    const [yyyy, mm] = g.ym.split('-')
                    const monthLabel = `${MONTH_NAMES[parseInt(mm, 10) - 1]} ${yyyy}`
                    return (
                      <Fragment key={g.ym}>
                        <tr>
                          <td colSpan={6} className="px-2 py-2">
                            <div className="text-[10px] uppercase tracking-wider font-semibold text-gray-500 dark:text-gray-400">
                              {monthLabel}
                            </div>
                          </td>
                        </tr>
                        {g.items.map(d => {
                          const a = d.asset_id ? assetById.get(d.asset_id) : null
                          const fi = fiById.get(d.financial_institution_id)
                          return (
                            <tr
                              key={d.id}
                              onClick={() => setSelected(d)}
                              className="border-t border-gray-100 dark:border-gray-800 hover:bg-gray-50 dark:hover:bg-gray-800/30 transition-colors cursor-pointer"
                            >
                              <td className="px-2 py-2 tnum text-gray-500 dark:text-gray-400">
                                {fmtDate(d.event_date)}
                              </td>
                              <td className="px-2">
                                <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] uppercase tracking-wider bg-amber-500/15 text-amber-700 dark:text-amber-400">
                                  {d.type_label}
                                </span>
                              </td>
                              <td className="px-2">
                                <div className="min-w-0">
                                  {a ? (
                                    <>
                                      <div className="font-mono font-medium flex items-center gap-1.5 text-gray-900 dark:text-gray-100">
                                        {a.ticker || a.name}
                                      </div>
                                      <div className="text-[11px] text-gray-500 truncate max-w-[260px]">
                                        {a.name} <span className="text-gray-400 dark:text-gray-600">· {fi?.short_name}</span>
                                      </div>
                                    </>
                                  ) : (
                                    <div className="text-[12px] italic text-gray-500 flex items-center gap-1.5">
                                      Sem ticker
                                      <span className="text-[10px] uppercase tracking-wider text-gray-400 dark:text-gray-600">
                                        via {fi?.short_name}
                                      </span>
                                    </div>
                                  )}
                                </div>
                              </td>
                              <td className="px-2 text-right tnum money text-gray-500 dark:text-gray-400">
                                {fmtMoney(d.gross_amount, d.currency)}
                              </td>
                              <td className="px-2 text-right tnum money text-amber-600 dark:text-amber-400">
                                {d.tax && d.tax > 0 ? '−' + fmtMoney(d.tax, d.currency) : '—'}
                              </td>
                              <td className="px-2 text-right">
                                <div className="tnum money font-medium text-emerald-500 dark:text-emerald-400">
                                  {fmtMoney(d.net_amount, d.currency, { sign: true })}
                                </div>
                              </td>
                            </tr>
                          )
                        })}
                      </Fragment>
                    )
                  })}
                </tbody>
              </table>
              {sorted.length === 0 && !loading && (
                <div className="py-12 text-center text-[12px] text-gray-500">
                  Sem proventos com esses filtros.
                </div>
              )}
            </div>
          </Card>
        )}

        {!loading && view === 'asset' && (
          <Card padding="p-3">
            <div className="overflow-x-auto -mx-1">
              <table className="w-full text-[12px]">
                <thead>
                  <tr className="text-[10px] uppercase tracking-wider text-gray-500">
                    <th className="text-left font-medium px-2 py-2">Ativo</th>
                    <th className="text-left font-medium px-2 py-2">Custodiante</th>
                    <th className="text-right font-medium px-2 py-2">Eventos</th>
                    <th className="text-right font-medium px-2 py-2">Total (BRL)</th>
                  </tr>
                </thead>
                <tbody>
                  {assetRows.map((row, i) => {
                    const a = row.asset_id ? assetById.get(row.asset_id) : null
                    const fi = fiById.get(row.fi_id)
                    return (
                      <tr
                        key={i}
                        onClick={() => {
                          if (a) navigate(`/assets/${a.id}`)
                        }}
                        className={`border-t border-gray-100 dark:border-gray-800 hover:bg-gray-50 dark:hover:bg-gray-800/30 transition-colors ${a ? 'cursor-pointer' : ''}`}
                      >
                        <td className="px-2 py-2.5">
                          {a ? (
                            <div className="flex items-center gap-2">
                              <span
                                className="w-1 h-5 rounded-full"
                                style={{ background: KLASS[collapsedOf(a.asset_class)].color }}
                              />
                              <div>
                                <div className="font-mono font-medium text-gray-900 dark:text-gray-100">
                                  {a.ticker || a.name}
                                </div>
                                <div className="text-[11px] text-gray-500 truncate max-w-[220px]">{a.name}</div>
                              </div>
                            </div>
                          ) : (
                            <span className="text-[12px] italic text-gray-500">Sem ticker (via {fi?.short_name})</span>
                          )}
                        </td>
                        <td className="px-2 text-[11px] text-gray-500 dark:text-gray-400">
                          {fi?.short_name}
                        </td>
                        <td className="px-2 text-right tnum">{row.count}</td>
                        <td className="px-2 text-right tnum money font-medium">
                          {fmtBRL(row.total, { compact: true })}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
              {assetRows.length === 0 && (
                <div className="py-12 text-center text-[12px] text-gray-500">
                  Sem proventos com esses filtros.
                </div>
              )}
            </div>
          </Card>
        )}
      </div>

      {/* Composer modal */}
      {composerOpen && (
        <DistributionComposer
          initial={editing}
          institutions={institutions}
          assets={assets}
          onSave={handleSave}
          onClose={() => { setComposerOpen(false); setEditing(undefined) }}
        />
      )}

      {/* Detail panel */}
      {selected && (
        <DistributionDetailPanel
          distribution={selected}
          asset={selected.asset_id ? assetById.get(selected.asset_id) || null : null}
          fi={fiById.get(selected.financial_institution_id) || null}
          onClose={() => setSelected(null)}
          onEdit={() => { setEditing(selected); setComposerOpen(true) }}
          onDeactivate={() => setConfirmDeactivate(selected)}
        />
      )}

      {/* Confirm deactivate */}
      {confirmDeactivate && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/40">
          <div className="w-full max-w-sm bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-700 shadow-xl p-6">
            <h2 className="text-base font-semibold text-gray-900 dark:text-white mb-2">Desativar provento?</h2>
            <p className="text-sm text-gray-500 dark:text-gray-400 mb-6">
              <strong>{confirmDeactivate.type_label}</strong>
              {confirmDeactivate.asset_ticker ? <> de <strong>{confirmDeactivate.asset_ticker}</strong></> : null}
              {' '}será desativado.
            </p>
            <div className="flex justify-end gap-3">
              <button
                onClick={() => setConfirmDeactivate(null)}
                className="px-4 py-2 rounded-lg text-sm text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
              >
                Cancelar
              </button>
              <button
                onClick={() => handleDeactivate(confirmDeactivate)}
                className="px-4 py-2 rounded-lg bg-red-600 hover:bg-red-700 text-white text-sm font-medium transition-colors"
              >
                Desativar
              </button>
            </div>
          </div>
        </div>
      )}
    </AppLayout>
  )
}
