/* Spec 35 — /snapshots: list of monthly snapshots + next-job card. */
import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { ArrowRight, ChevronRight, Plus } from 'lucide-react'

import { api, type SnapshotOut, type UserOut } from '../lib/api'
import { fmtBRL, fmtUSD } from '../lib/money'
import AppLayout from '../components/AppLayout'
import StatusPill from '../components/StatusPill'
import Sparkline from '../components/Sparkline'
import { Card, PageHeader } from '../components/ui'

const MONTH_NAMES = [
  'Jan', 'Fev', 'Mar', 'Abr', 'Mai', 'Jun',
  'Jul', 'Ago', 'Set', 'Out', 'Nov', 'Dez',
]

function ymLabel(ym: string): string {
  const [y, m] = ym.split('-')
  return `${MONTH_NAMES[parseInt(m, 10) - 1]}/${y.slice(2)}`
}

function periodYm(period: string): string {
  return period.slice(0, 7)
}

function nextFirstOfMonthBRT(now: Date = new Date()): Date {
  // The job runs at 06:30 BRT on day 1 of every month. Compute the
  // upcoming occurrence in local time for display.
  const next = new Date(now)
  next.setDate(1)
  next.setMonth(next.getMonth() + 1)
  next.setHours(6, 30, 0, 0)
  return next
}

function apuracaoTarget(today: Date = new Date()): { ym: string; label: string } {
  // period_end is the LAST CALENDAR DAY of the month (weekend/holiday OK —
  // PTAX walks back). Target = current month iff today >= last day of it.
  const lastCalDay = new Date(today.getFullYear(), today.getMonth() + 1, 0)
  const useCurrent = today.getTime() >= lastCalDay.getTime()
  const year = useCurrent
    ? today.getFullYear()
    : today.getMonth() === 0 ? today.getFullYear() - 1 : today.getFullYear()
  const monthIdx = useCurrent
    ? today.getMonth()
    : today.getMonth() === 0 ? 11 : today.getMonth() - 1
  const ym = `${year}-${String(monthIdx + 1).padStart(2, '0')}`
  return { ym, label: `${MONTH_NAMES[monthIdx]}/${String(year).slice(2)}` }
}

export default function Snapshots() {
  const navigate = useNavigate()
  const [me, setMe] = useState<UserOut | null>(null)
  const [snaps, setSnaps] = useState<SnapshotOut[]>([])
  const [loading, setLoading] = useState(true)
  const [creating, setCreating] = useState(false)

  useEffect(() => {
    api.me().then(setMe).catch(() => navigate('/login'))
  }, [navigate])

  useEffect(() => {
    if (!me) return
    setLoading(true)
    api.listSnapshots().then(setSnaps).finally(() => setLoading(false))
  }, [me])

  const inReview = useMemo(() => snaps.find(s => s.status === 'IN_REVIEW') ?? null, [snaps])
  const latestClosed = useMemo(
    () => snaps.find(s => s.status === 'CLOSED') ?? null,
    [snaps],
  )

  const sparkData = useMemo(
    () => [...snaps]
      .filter(s => s.status === 'CLOSED')
      .sort((a, b) => a.period_end_date.localeCompare(b.period_end_date))
      .slice(-12)
      .map(s => Number(s.total_value_brl)),
    [snaps],
  )

  const target = useMemo(() => apuracaoTarget(), [])
  // Se o target já tem snapshot (qualquer status), o botão muda de função:
  // IN_REVIEW → leva pra ele; CLOSED → esconde (já tá fechado, nada a fazer).
  const targetSnap = useMemo(
    () => snaps.find(s => periodYm(s.period_end_date) === target.ym) ?? null,
    [snaps, target.ym],
  )

  async function handleApurar() {
    setCreating(true)
    try {
      const s = await api.createSnapshot({ target_ym: target.ym, auto: true })
      navigate(`/snapshots/${periodYm(s.period_end_date)}`)
    } catch (e) {
      alert(e instanceof Error ? e.message : 'Erro')
    } finally {
      setCreating(false)
    }
  }

  if (!me) return null

  const next = nextFirstOfMonthBRT()

  return (
    <AppLayout user={me}>
      <div className="space-y-6">
        <PageHeader
          title="Fechamentos"
          count={snaps.length}
          countLabel="apurações no histórico"
          action={
            targetSnap?.status === 'CLOSED' ? null
              : targetSnap?.status === 'IN_REVIEW' ? (
                <Link
                  to={`/snapshots/${periodYm(targetSnap.period_end_date)}`}
                  className="h-8 px-3 inline-flex items-center gap-1.5 rounded-lg text-[12px] bg-amber-500 hover:bg-amber-400 text-white transition-colors"
                >
                  <ArrowRight className="w-3.5 h-3.5" /> Continuar {target.label}
                </Link>
              ) : (
                <button
                  onClick={handleApurar}
                  disabled={creating}
                  className="h-8 px-3 inline-flex items-center gap-1.5 rounded-lg text-[12px] bg-indigo-500 hover:bg-indigo-400 disabled:opacity-50 text-white transition-colors"
                >
                  <Plus className="w-3.5 h-3.5" /> Apurar {target.label}
                </button>
              )
          }
        />

        {/* Hero — in-review + next-job */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          {inReview ? (
            <Card className="lg:col-span-2 border-amber-200 dark:border-amber-900">
              <div className="text-[10px] uppercase tracking-wider text-amber-700 dark:text-amber-400 font-semibold">
                Apuração em revisão
              </div>
              <div className="mt-1 flex items-center gap-2 flex-wrap">
                <Link
                  to={`/snapshots/${periodYm(inReview.period_end_date)}`}
                  className="text-2xl font-semibold tnum hover:text-indigo-500 dark:hover:text-indigo-300"
                >
                  {ymLabel(periodYm(inReview.period_end_date))}
                </Link>
                <StatusPill status={inReview.status} />
                <span className="text-[11px] text-gray-500">
                  {inReview.pendencies_open} pendência{inReview.pendencies_open === 1 ? '' : 's'} abertas
                </span>
              </div>
              <Link
                to={`/snapshots/${periodYm(inReview.period_end_date)}`}
                className="mt-2 inline-flex items-center gap-1 text-[12px] text-indigo-500 dark:text-indigo-400 hover:underline"
              >
                Resolver pendências <ChevronRight className="w-3 h-3" />
              </Link>
            </Card>
          ) : (
            <Card className="lg:col-span-2">
              <div className="text-[10px] uppercase tracking-wider text-gray-500 font-semibold">
                Último fechamento
              </div>
              {latestClosed ? (
                <>
                  <div className="mt-1 flex items-center gap-2 flex-wrap">
                    <Link
                      to={`/snapshots/${periodYm(latestClosed.period_end_date)}`}
                      className="text-2xl font-semibold tnum hover:text-indigo-500 dark:hover:text-indigo-300"
                    >
                      {ymLabel(periodYm(latestClosed.period_end_date))}
                    </Link>
                    <StatusPill status={latestClosed.status} />
                  </div>
                  <div className="text-2xl font-semibold tnum mt-1">
                    {fmtBRL(Number(latestClosed.total_value_brl))}
                  </div>
                  {sparkData.length >= 2 && (
                    <div className="mt-2">
                      <Sparkline data={sparkData} w={320} h={50} color="#6366f1" />
                    </div>
                  )}
                </>
              ) : (
                <div className="text-[12px] text-gray-500 mt-2">Sem fechamentos ainda.</div>
              )}
            </Card>
          )}

          <Card>
            <div className="text-[10px] uppercase tracking-wider text-gray-500 font-semibold">
              Próxima execução automática
            </div>
            <div className="mt-1 text-base font-semibold">
              {next.toLocaleDateString('pt-BR', { day: '2-digit', month: 'long' })}
            </div>
            <div className="text-[11px] text-gray-500">
              {next.toLocaleDateString('pt-BR', { weekday: 'long' })}, 06:30 BRT
            </div>
            <div className="text-[11px] text-gray-500 mt-2">
              Roda automaticamente no 1º do mês e captura o fechamento do mês anterior.
            </div>
          </Card>
        </div>

        {/* History table */}
        <Card padding="p-3">
          {loading ? (
            <div className="py-8 text-center text-[12px] text-gray-500">Carregando…</div>
          ) : snaps.length === 0 ? (
            <div className="py-8 text-center text-[12px] text-gray-500">
              Nenhuma apuração ainda. Clique em "Apurar mês anterior" para criar a primeira.
            </div>
          ) : (
            <div className="overflow-x-auto -mx-1">
              <table className="w-full text-[12px]">
                <thead>
                  <tr className="text-[10px] uppercase tracking-wider text-gray-500">
                    <th className="text-left font-medium px-2 py-2">Período</th>
                    <th className="text-left font-medium px-2 py-2">Status</th>
                    <th className="text-right font-medium px-2 py-2">Patrimônio</th>
                    <th className="text-right font-medium px-2 py-2">Itens</th>
                    <th className="text-left font-medium px-2 py-2">Origem</th>
                    <th className="text-right font-medium px-2 py-2">Pendências</th>
                    <th className="px-2"></th>
                  </tr>
                </thead>
                <tbody>
                  {snaps.map(s => {
                    const ym = periodYm(s.period_end_date)
                    return (
                      <tr
                        key={s.id}
                        onClick={() => navigate(`/snapshots/${ym}`)}
                        className="border-t border-gray-100 dark:border-gray-800 hover:bg-gray-50 dark:hover:bg-gray-800/30 transition-colors cursor-pointer"
                        data-testid={`snapshot-row-${ym}`}
                      >
                        <td className="px-2 py-2.5 font-medium">
                          {ymLabel(ym)}
                          <span className="text-[10px] text-gray-500 ml-1 tnum">
                            {s.period_end_date}
                          </span>
                        </td>
                        <td className="px-2"><StatusPill status={s.status} /></td>
                        <td className="px-2 text-right">
                          <div className="tnum money font-medium">
                            {fmtBRL(Number(s.total_value_brl), { compact: true })}
                          </div>
                          <div className="tnum money text-[10px] text-gray-500 dark:text-gray-600">
                            {fmtUSD(Number(s.total_value_usd), { compact: true })}
                          </div>
                        </td>
                        <td className="px-2 text-right tnum text-gray-500">{s.items_count}</td>
                        <td className="px-2 text-[10px] uppercase tracking-wider text-gray-500">
                          {s.source}
                        </td>
                        <td className="px-2 text-right tnum">
                          {s.pendencies_total === 0 ? (
                            <span className="text-gray-400">—</span>
                          ) : s.pendencies_open === 0 ? (
                            <span className="text-emerald-600 dark:text-emerald-400">
                              {s.pendencies_total} ✓
                            </span>
                          ) : (
                            <span className="text-amber-600 dark:text-amber-400">
                              {s.pendencies_open}/{s.pendencies_total}
                            </span>
                          )}
                        </td>
                        <td className="px-2 text-gray-400"><ChevronRight className="w-4 h-4" /></td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>
    </AppLayout>
  )
}
