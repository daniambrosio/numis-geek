import type { ChartCurrency, ChartDataOut, ChartRowOut } from './api'

/** Abbreviated month names indexed 0=Jan ... 11=Dez. */
const MONTH_ABBR_PT = [
  'Jan', 'Fev', 'Mar', 'Abr', 'Mai', 'Jun',
  'Jul', 'Ago', 'Set', 'Out', 'Nov', 'Dez',
]

/** "2026-04" → "Abr" (or "Abr/26" when crossing year). */
export function monthLabel(ym: string, includeYear = false): string {
  const m = Number(ym.slice(5, 7))
  if (!m || m < 1 || m > 12) return ym
  const base = MONTH_ABBR_PT[m - 1]
  if (!includeYear) return base
  const yy = ym.slice(2, 4)
  return `${base}/${yy}`
}

/** Format a numeric value for chart axis / KPI display.
 *
 * compact=true → "R$ 5,2k", "R$ 1,2M", "R$ 0"
 * compact=false → "R$ 5.231", "US$ 1.231" (no decimals)
 */
export function fmtChart(
  value: number,
  ccy: ChartCurrency,
  compact = false,
): string {
  const symbol = ccy === 'USD' ? 'US$' : 'R$'

  if (value === 0) return `${symbol} 0`

  const abs = Math.abs(value)
  const sign = value < 0 ? '-' : ''

  if (compact) {
    if (abs >= 1_000_000) {
      const m = (abs / 1_000_000).toLocaleString('pt-BR', { maximumFractionDigits: 1 })
      return `${sign}${symbol} ${m}M`
    }
    if (abs >= 1_000) {
      const k = (abs / 1_000).toLocaleString('pt-BR', { maximumFractionDigits: 1 })
      return `${sign}${symbol} ${k}k`
    }
    return `${sign}${symbol} ${abs.toLocaleString('pt-BR', { maximumFractionDigits: 0 })}`
  }

  return `${sign}${symbol} ${abs.toLocaleString('pt-BR', { maximumFractionDigits: 0 })}`
}

/** Percentage formatter for tooltip share. */
export function fmtPct(decimal: number, dp = 1): string {
  return `${(decimal * 100).toFixed(dp).replace('.', ',')}%`
}

export interface ChartKpis {
  lastMonthTotal: number
  /** decimal (e.g. 0.12 = +12%); null when no previous month with value > 0 */
  momPct: number | null
  trailingSum: number
  monthlyAvg: number
  ytdSum: number
  max: number
}

/** Compute the header KPIs from a ChartDataOut.
 *
 * "Último mês" = último mês CALENDÁRIO FECHADO (não o mês corrente, que
 * provavelmente ainda não tem proventos pagos). Em junho/2026, "último
 * mês" = maio. MoM compara esse último fechado vs o anterior. */
export function computeKpis(
  data: ChartDataOut,
  today: Date = new Date(),
): ChartKpis {
  const rows = data.rows
  const currentYM = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}`

  // Drop the in-progress current month from "last month" detection.
  const closedRows = rows.filter(r => r.ym < currentYM)
  const last = closedRows[closedRows.length - 1]
  const prev = closedRows[closedRows.length - 2]
  const lastMonthTotal = last?.total ?? 0
  const prevTotal = prev?.total ?? 0
  const momPct = prev && prevTotal > 0
    ? (lastMonthTotal - prevTotal) / prevTotal
    : null

  const trailingSum = data.totals.sum
  const monthlyAvg = data.totals.monthly_avg
  const max = data.totals.max

  const ytdSum = rows
    .filter(r => r.ym.startsWith(String(today.getFullYear())) && r.ym <= currentYM)
    .reduce((s, r) => s + r.total, 0)

  return { lastMonthTotal, momPct, trailingSum, monthlyAvg, ytdSum, max }
}

/** Decide whether the x-axis should label every other month (when >14 cols). */
export function shouldStrideXAxis(rowCount: number): boolean {
  return rowCount > 14
}

/** Pick which x-axis ticks to show given stride rule. */
export function xAxisTicks(rows: ChartRowOut[]): { ym: string; show: boolean }[] {
  const stride = shouldStrideXAxis(rows.length)
  return rows.map((r, i) => ({ ym: r.ym, show: !stride || i % 2 === 0 }))
}
