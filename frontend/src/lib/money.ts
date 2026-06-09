/* Formatters de valor monetário system-wide.
 *
 * Formato compact usa "k" (mil) e "M" (milhão) em vez de "mil"/"mi"
 * (Intl.NumberFormat com notation: 'compact' em pt-BR usa "mil"/"mi",
 * que confunde leitura visual). Decimal com vírgula, sem espaço entre
 * número e sufixo: "R$ 1,5k", "R$ 12,5M", "-US$ 3,2k".
 */

interface FmtOpts {
  compact?: boolean
  decimals?: number
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

export function fmtBRL(n: number, opts: FmtOpts = {}): string {
  if (opts.compact) {
    return fmtCompact(n, 'R$', () =>
      n.toLocaleString('pt-BR', {
        style: 'currency', currency: 'BRL',
        minimumFractionDigits: opts.decimals ?? 0,
        maximumFractionDigits: opts.decimals ?? 0,
      }),
    )
  }
  return n.toLocaleString('pt-BR', {
    style: 'currency', currency: 'BRL',
    minimumFractionDigits: opts.decimals ?? 2,
    maximumFractionDigits: opts.decimals ?? 2,
  })
}

export function fmtUSD(n: number, opts: FmtOpts = {}): string {
  if (opts.compact) {
    return fmtCompact(n, 'US$', () =>
      n.toLocaleString('en-US', {
        style: 'currency', currency: 'USD',
        minimumFractionDigits: opts.decimals ?? 0,
        maximumFractionDigits: opts.decimals ?? 0,
      }),
    )
  }
  return n.toLocaleString('en-US', {
    style: 'currency', currency: 'USD',
    minimumFractionDigits: opts.decimals ?? 2,
    maximumFractionDigits: opts.decimals ?? 2,
  })
}

export function fmtMoney(
  n: number,
  currency: 'BRL' | 'USD',
  opts: FmtOpts = {},
): string {
  return currency === 'USD' ? fmtUSD(n, opts) : fmtBRL(n, opts)
}
