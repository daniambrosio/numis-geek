// Visual tokens — mirror the prototype's KLASS and FI palette.
// Legacy class codes (STOCK_BR, STOCK_US, FII, BOND) collapse to their
// merge targets — TODO(spec-09): drop legacy aliases after backend collapse.

export type CollapsedClassCode =
  | 'STOCK'
  | 'REIT'
  | 'ETF'
  | 'FIXED_INCOME'
  | 'FUND'
  | 'CRYPTO'
  | 'REAL_ESTATE'
  | 'VEHICLE'
  | 'CASH'
  | 'FGTS'
  | 'PRIVATE_PENSION'

export interface ClassToken {
  color: string   // hex, used inline for dots / vertical bars
  label: string
}

export const KLASS: Record<CollapsedClassCode, ClassToken> = {
  STOCK:           { color: '#3b82f6', label: 'Ação' },
  REIT:            { color: '#22c55e', label: 'FII / REIT' },
  ETF:             { color: '#8b5cf6', label: 'ETF' },
  FIXED_INCOME:    { color: '#f59e0b', label: 'Renda Fixa' },
  FUND:            { color: '#14b8a6', label: 'Fundo' },
  CRYPTO:          { color: '#eab308', label: 'Cripto' },
  REAL_ESTATE:     { color: '#ec4899', label: 'Imóvel' },
  VEHICLE:         { color: '#ef4444', label: 'Veículo' },
  CASH:            { color: '#64748b', label: 'Dinheiro' },
  FGTS:            { color: '#84cc16', label: 'FGTS' },
  PRIVATE_PENSION: { color: '#06b6d4', label: 'Previdência' },
}

// Backend uses 14 codes today. Map every legacy code to its collapsed target.
// Order of `members` defines which raw codes a "click on Ação" filters in.
export const COLLAPSED_OF: Record<string, CollapsedClassCode> = {
  STOCK_BR: 'STOCK',
  STOCK_US: 'STOCK',
  STOCK: 'STOCK',
  FII: 'REIT',
  REIT: 'REIT',
  ETF: 'ETF',
  BOND: 'FIXED_INCOME',
  FIXED_INCOME: 'FIXED_INCOME',
  FUND: 'FUND',
  CRYPTO: 'CRYPTO',
  REAL_ESTATE: 'REAL_ESTATE',
  VEHICLE: 'VEHICLE',
  CASH: 'CASH',
  FGTS: 'FGTS',
  PRIVATE_PENSION: 'PRIVATE_PENSION',
}

export function collapsedOf(rawClass: string): CollapsedClassCode {
  return COLLAPSED_OF[rawClass] ?? 'STOCK'
}

// Financial institution palette — keyed by `logo_slug` from the backend.
// Values mirror the prototype's FIs[] entries.
export interface FIToken {
  color: string
  initials: string
}

export const FI_PALETTE: Record<string, FIToken> = {
  xp:           { color: '#FFCB05', initials: 'XP' },
  avenue:       { color: '#0066FF', initials: 'AV' },
  itau:         { color: '#EC7000', initials: 'IT' },
  btg:          { color: '#0F2F4A', initials: 'BT' },
  bradesco:     { color: '#CC092F', initials: 'BR' },
  santander:    { color: '#EC0000', initials: 'SA' },
  caixa:        { color: '#0070AF', initials: 'CA' },
  wise:         { color: '#9FE870', initials: 'WI' },
  coinbase:     { color: '#0052FF', initials: 'CB' },
  mercadopago:  { color: '#00B1EA', initials: 'MP' },
  clear:        { color: '#1FAA59', initials: 'CL' },
  nubank:       { color: '#820AD1', initials: 'NU' },
  particular:   { color: '#6B7280', initials: 'PA' },
  fix:          { color: '#94a3b8', initials: 'FX' },
}

export function fiTokenFor(slug: string | null | undefined, shortName: string): FIToken {
  if (slug && FI_PALETTE[slug]) return FI_PALETTE[slug]
  // Fallback — derive initials from short name.
  const initials = shortName.split(/\s+/).slice(0, 2).map(s => s[0] ?? '').join('').toUpperCase() || '··'
  return { color: '#94a3b8', initials }
}
