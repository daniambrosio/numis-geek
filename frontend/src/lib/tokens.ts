// Visual tokens — mirror the prototype's KLASS and FI palette.
// Spec 09 landed: backend now uses the 11 collapsed classes natively.

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

// Identity map kept for callers that still go through collapsedOf().
// Backend uses the 11 collapsed codes natively as of spec 09.
export function collapsedOf(rawClass: string): CollapsedClassCode {
  return (rawClass as CollapsedClassCode) in KLASS
    ? (rawClass as CollapsedClassCode)
    : 'STOCK'
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

// AssetMovement type palette — mirror prototype's typeOpts.
export const AM_TYPE_COLORS: Record<string, string> = {
  BUY: '#3b82f6',              // blue
  SELL: '#ef4444',             // red
  BONUS: '#22c55e',            // green
  SUBSCRIPTION: '#8b5cf6',     // violet
  COME_COTAS: '#f59e0b',       // amber
  FULL_REDEMPTION: '#14b8a6',  // teal
}

// Distribution type palette
export const DIST_TYPE_COLORS: Record<string, string> = {
  DIVIDEND: '#a78bfa',           // violet light
  INTEREST: '#06b6d4',           // cyan
  JCP: '#10b981',                // emerald
  SECURITIES_LENDING: '#f97316', // orange
}

export function amTypeColor(type: string): string {
  return AM_TYPE_COLORS[type] ?? DIST_TYPE_COLORS[type] ?? '#94a3b8'
}

// Backward-compat alias (used in a few components still importing `lanTypeColor`).
export const lanTypeColor = amTypeColor

export function fiTokenFor(slug: string | null | undefined, shortName: string): FIToken {
  if (slug && FI_PALETTE[slug]) return FI_PALETTE[slug]
  // Fallback — derive initials from short name.
  const initials = shortName.split(/\s+/).slice(0, 2).map(s => s[0] ?? '').join('').toUpperCase() || '··'
  return { color: '#94a3b8', initials }
}
