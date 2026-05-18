import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { RefreshCw, Database, Calendar, Clock } from 'lucide-react'
import {
  api,
  type PTAXListOut,
  type PTAXStatusOut,
  type PTAXSyncMode,
  type PTAXSyncResultOut,
  type UserOut,
} from '../../lib/api'
import AppLayout from '../../components/AppLayout'
import { Card, PageHeader } from '../../components/ui'

const PAGE_SIZE = 50

function formatDate(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit', year: 'numeric' })
}

function formatDateTime(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' })
}

function Kpi({ icon: Icon, label, value, hint }: {
  icon: typeof Database
  label: string
  value: string
  hint?: string
}) {
  return (
    <Card>
      <div className="flex items-start gap-3">
        <div className="w-10 h-10 rounded-lg bg-indigo-500/10 dark:bg-indigo-500/20 flex items-center justify-center shrink-0">
          <Icon className="w-5 h-5 text-indigo-600 dark:text-indigo-400" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-xs uppercase tracking-wide text-gray-500 dark:text-gray-400">{label}</div>
          <div className="font-mono text-base font-semibold text-gray-900 dark:text-white mt-0.5">{value}</div>
          {hint && <div className="text-xs text-gray-400 dark:text-gray-600 mt-0.5">{hint}</div>}
        </div>
      </div>
    </Card>
  )
}

export default function SysAdminPTAX() {
  const navigate = useNavigate()
  const [me, setMe] = useState<UserOut | null>(null)
  const [status, setStatus] = useState<PTAXStatusOut | null>(null)
  const [list, setList] = useState<PTAXListOut | null>(null)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(true)
  const [syncing, setSyncing] = useState<PTAXSyncMode | null>(null)
  const [lastSync, setLastSync] = useState<PTAXSyncResultOut | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    api.me()
      .then(u => {
        if (u.role !== 'sysadmin') navigate('/dashboard')
        setMe(u)
      })
      .catch(() => navigate('/login'))
  }, [navigate])

  async function refresh() {
    const [st, ls] = await Promise.all([
      api.ptaxStatus(),
      api.listPtax(page, PAGE_SIZE),
    ])
    setStatus(st)
    setList(ls)
  }

  useEffect(() => {
    if (!me) return
    setLoading(true)
    refresh().finally(() => setLoading(false))
  }, [me, page])

  async function handleSync(mode: PTAXSyncMode) {
    setSyncing(mode)
    setError('')
    try {
      const result = await api.syncPtax(mode)
      setLastSync(result)
      setPage(1)
      await refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Erro ao sincronizar.')
    } finally {
      setSyncing(null)
    }
  }

  if (!me) return null

  const totalPages = list ? Math.max(1, Math.ceil(list.total / list.page_size)) : 1

  return (
    <AppLayout user={me}>
      <div className="space-y-6">
        <PageHeader
          title="PTAX USD/BRL"
          count={status?.total_rows ?? 0}
          countLabel="taxa(s)"
          action={
            <div className="flex items-center gap-2">
              <button
                onClick={() => handleSync('incremental')}
                disabled={syncing !== null}
                className="h-8 px-3 inline-flex items-center gap-1.5 rounded-lg text-[12px] bg-indigo-500 hover:bg-indigo-400 disabled:opacity-50 text-white transition-colors"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${syncing === 'incremental' ? 'animate-spin' : ''}`} />
                {syncing === 'incremental' ? 'Sincronizando…' : 'Sync incremental'}
              </button>
              <button
                onClick={() => handleSync('full')}
                disabled={syncing !== null}
                className="h-8 px-3 inline-flex items-center gap-1.5 rounded-lg text-[12px] border border-gray-300 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-800 disabled:opacity-50 text-gray-700 dark:text-gray-300 transition-colors"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${syncing === 'full' ? 'animate-spin' : ''}`} />
                Sync full
              </button>
            </div>
          }
        />

        {/* KPIs */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          <Kpi icon={Database} label="Total de taxas" value={status?.total_rows?.toLocaleString('pt-BR') ?? '—'} />
          <Kpi icon={Calendar} label="Mais recente" value={formatDate(status?.last_date ?? null)} />
          <Kpi icon={Calendar} label="Mais antiga" value={formatDate(status?.oldest_date ?? null)} />
          <Kpi icon={Clock} label="Última busca" value={formatDateTime(status?.last_fetched_at ?? null)} />
        </div>

        {lastSync && (
          <div className="text-sm bg-emerald-50 dark:bg-emerald-900/20 border border-emerald-200 dark:border-emerald-900 rounded-xl px-4 py-3 text-emerald-700 dark:text-emerald-300">
            <strong className="capitalize">{lastSync.mode}</strong> sync:&nbsp;
            {lastSync.inserted_count} inserida(s), {lastSync.updated_count} atualizada(s) entre&nbsp;
            <strong>{formatDate(lastSync.range_start)}</strong> e <strong>{formatDate(lastSync.range_end)}</strong>
            &nbsp;({lastSync.duration_ms} ms)
          </div>
        )}

        {error && (
          <div className="text-sm bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-900 rounded-xl px-4 py-3 text-red-700 dark:text-red-300">
            {error}
          </div>
        )}

        {/* Table */}
        <Card padding="p-0"><div className="overflow-hidden rounded-2xl">
          {loading ? (
            <div className="p-12 text-center text-sm text-gray-400 dark:text-gray-600">Carregando…</div>
          ) : (
            <>
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-200 dark:border-gray-800">
                    {['Data', 'PTAX (USD→BRL)', 'Fonte', 'Capturada em'].map((h, i) => (
                      <th key={i} className="text-left px-4 py-3 text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
                  {list?.items.map(r => (
                    <tr key={r.id} className="hover:bg-gray-50 dark:hover:bg-gray-800/50 transition-colors">
                      <td className="px-4 py-2 text-gray-900 dark:text-white font-medium tnum">{formatDate(r.date)}</td>
                      <td className="px-4 py-2 text-gray-900 dark:text-white font-mono tnum">{Number(r.rate).toFixed(4)}</td>
                      <td className="px-4 py-2 text-gray-500 dark:text-gray-400 text-xs">{r.source}</td>
                      <td className="px-4 py-2 text-gray-400 dark:text-gray-600 text-xs">{formatDateTime(r.fetched_at)}</td>
                    </tr>
                  ))}
                  {list?.items.length === 0 && (
                    <tr>
                      <td colSpan={4} className="px-4 py-12 text-center text-sm text-gray-400 dark:text-gray-600">
                        Nenhuma taxa carregada. Clique em "Sync full" pra fazer o backfill inicial.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
              {list && totalPages > 1 && (
                <div className="flex items-center justify-between px-4 py-3 border-t border-gray-100 dark:border-gray-800 text-xs text-gray-500 dark:text-gray-400">
                  <div>Página {page} de {totalPages}</div>
                  <div className="flex gap-2">
                    <button
                      onClick={() => setPage(p => Math.max(1, p - 1))}
                      disabled={page <= 1}
                      className="px-3 py-1 rounded-lg border border-gray-200 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-800 disabled:opacity-50"
                    >
                      Anterior
                    </button>
                    <button
                      onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                      disabled={page >= totalPages}
                      className="px-3 py-1 rounded-lg border border-gray-200 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-800 disabled:opacity-50"
                    >
                      Próxima
                    </button>
                  </div>
                </div>
              )}
            </>
          )}
        </div></Card>
      </div>
    </AppLayout>
  )
}
