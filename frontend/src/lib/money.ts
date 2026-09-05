/* Formatters de valor monetário system-wide.
 *
 * Formato compact usa "k" (mil) e "M" (milhão) em vez de "mil"/"mi"
 * (Intl.NumberFormat com notation: 'compact' em pt-BR usa "mil"/"mi",
 * que confunde leitura visual). Decimal com vírgula, sem espaço entre
 * número e sufixo: "R$ 1,5k", "R$ 12,5M", "-US$ 3,2k".
 *
 * `null`/`undefined` viram "—" (spec 81 — antes cada página tinha a sua
 * cópia null-safe). `sign: true` prefixa "+"/"−" (P&L, variação).
 */

export interface FmtOpts {
  compact?: boolean
  decimals?: number
  /** Prefixa "+" (≥ 0) ou "−" (< 0) — pra P&L e deltas. */
  sign?: boolean
}

function compactNumeric(abs: number): { value: string; suffix: string } | null {
  if (abs >= 1_000_000) {
    return {
      value: (abs / 1_000_000).toFixed(1).replace('.', ','),
      suffix: 'M',
    }
  }
  if (abs >= 1_000) {
    return {
      value: (abs / 1_000).toFixed(1).replace('.', ','),
      suffix: 'k',
    }
  }
  return null
}

function fmtCompact(
  n: number,
  symbol: string,
  fallback: () => string,
): string {
  const abs = Math.abs(n)
  const c = compactNumeric(abs)
  if (!c) return fallback()
  const sign = n < 0 ? '-' : ''
  return `${sign}${symbol} ${c.value}${c.suffix}`
}

function withSign(n: number, formatAbs: (abs: number) => string): string {
  return (n >= 0 ? '+' : '−') + formatAbs(Math.abs(n))
}

function fmtCurrency(
  n: number | null | undefined,
  symbol: string,
  locale: string,
  currency: 'BRL' | 'USD',
  opts: FmtOpts,
): string {
  if (n == null || Number.isNaN(n)) return '—'
  const plain = (v: number) => {
    if (opts.compact) {
      return fmtCompact(v, symbol, () =>
        v.toLocaleString(locale, {
          style: 'currency', currency,
          minimumFractionDigits: opts.decimals ?? 0,
          maximumFractionDigits: opts.decimals ?? 0,
        }),
      )
    }
    return v.toLocaleString(locale, {
      style: 'currency', currency,
      minimumFractionDigits: opts.decimals ?? 2,
      maximumFractionDigits: opts.decimals ?? 2,
    })
  }
  return opts.sign ? withSign(n, plain) : plain(n)
}

export function fmtBRL(n: number | null | undefined, opts: FmtOpts = {}): string {
  return fmtCurrency(n, 'R$', 'pt-BR', 'BRL', opts)
}

export function fmtUSD(n: number | null | undefined, opts: FmtOpts = {}): string {
  return fmtCurrency(n, 'US$', 'en-US', 'USD', opts)
}

export function fmtMoney(
  n: number | null | undefined,
  currency: 'BRL' | 'USD' | string,
  opts: FmtOpts = {},
): string {
  return currency === 'USD' ? fmtUSD(n, opts) : fmtBRL(n, opts)
}
