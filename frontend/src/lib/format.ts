/* Formatters não-monetários compartilhados (spec 81 — extraídos de
 * pages/AssetDetail.tsx, onde viviam como cópias locais). Dinheiro fica em
 * lib/money.ts; percentuais de gráfico em lib/chart.ts. */

export function fmtNum(n: number | null | undefined, dp = 0): string {
  if (n == null) return '—'
  return new Intl.NumberFormat('pt-BR', {
    minimumFractionDigits: dp, maximumFractionDigits: dp,
  }).format(n)
}

/** 0.1234 → "12,3%" (dp=1). `sign` prefixa "+" quando > 0. */
export function fmtPct(n: number | null | undefined, dp = 1, sign = false): string {
  if (n == null || Number.isNaN(n)) return '—'
  const v = (n * 100).toFixed(dp).replace('.', ',')
  return (sign && n > 0 ? '+' : '') + v + '%'
}

/** ISO (YYYY-MM-DD ou datetime) → dd/mm/aaaa. */
export function fmtDate(iso: string): string {
  return new Intl.DateTimeFormat('pt-BR').format(
    new Date(iso + (iso.length === 10 ? 'T00:00:00' : '')),
  )
}

export const MONTH_SHORT_PT = [
  'jan', 'fev', 'mar', 'abr', 'mai', 'jun',
  'jul', 'ago', 'set', 'out', 'nov', 'dez',
]

/** "2026-08-31" → "ago/26". */
export function fmtMonthYY(iso: string): string {
  const [y, m] = iso.split('-')
  return `${MONTH_SHORT_PT[parseInt(m, 10) - 1]}/${y.slice(2)}`
}

/** Data LOCAL de hoje em YYYY-MM-DD. Nunca `toISOString().slice(0, 10)` —
 *  isso é UTC: no Brasil, depois das 21h, vira o dia seguinte. */
export function todayISO(d: Date = new Date()): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}
