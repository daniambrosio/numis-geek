// Visual tokens for asset classes and currencies. Defined here, consumed by
// future spec 17a/17b/etc. Until spec 09 collapses asset classes 14→11,
// legacy codes (STOCK_BR, STOCK_US, FII, BOND) alias to their merge targets.

export type AssetClassCode =
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
  // Legacy — TODO(spec-09): remove after asset_class collapse
  | 'STOCK_BR'
  | 'STOCK_US'
  | 'FII'
  | 'BOND'

export interface ClassToken {
  dot: string
  bg: string
  text: string
  border: string
  label: string
}

export const KLASS_COLORS: Record<AssetClassCode, ClassToken> = {
  STOCK: {
    dot: 'bg-blue-500',
    bg: 'bg-blue-100 dark:bg-blue-900/30',
    text: 'text-blue-700 dark:text-blue-300',
    border: 'border-blue-200 dark:border-blue-800',
    label: 'Ação',
  },
  REIT: {
    dot: 'bg-emerald-500',
    bg: 'bg-emerald-100 dark:bg-emerald-900/30',
    text: 'text-emerald-700 dark:text-emerald-300',
    border: 'border-emerald-200 dark:border-emerald-800',
    label: 'FII / REIT',
  },
  ETF: {
    dot: 'bg-violet-500',
    bg: 'bg-violet-100 dark:bg-violet-900/30',
    text: 'text-violet-700 dark:text-violet-300',
    border: 'border-violet-200 dark:border-violet-800',
    label: 'ETF',
  },
  FIXED_INCOME: {
    dot: 'bg-amber-500',
    bg: 'bg-amber-100 dark:bg-amber-900/30',
    text: 'text-amber-700 dark:text-amber-300',
    border: 'border-amber-200 dark:border-amber-800',
    label: 'Renda Fixa',
  },
  FUND: {
    dot: 'bg-teal-500',
    bg: 'bg-teal-100 dark:bg-teal-900/30',
    text: 'text-teal-700 dark:text-teal-300',
    border: 'border-teal-200 dark:border-teal-800',
    label: 'Fundo',
  },
  CRYPTO: {
    dot: 'bg-yellow-500',
    bg: 'bg-yellow-100 dark:bg-yellow-900/30',
    text: 'text-yellow-700 dark:text-yellow-300',
    border: 'border-yellow-200 dark:border-yellow-800',
    label: 'Cripto',
  },
  REAL_ESTATE: {
    dot: 'bg-pink-500',
    bg: 'bg-pink-100 dark:bg-pink-900/30',
    text: 'text-pink-700 dark:text-pink-300',
    border: 'border-pink-200 dark:border-pink-800',
    label: 'Imóvel',
  },
  VEHICLE: {
    dot: 'bg-rose-500',
    bg: 'bg-rose-100 dark:bg-rose-900/30',
    text: 'text-rose-700 dark:text-rose-300',
    border: 'border-rose-200 dark:border-rose-800',
    label: 'Veículo',
  },
  CASH: {
    dot: 'bg-slate-500',
    bg: 'bg-slate-100 dark:bg-slate-800',
    text: 'text-slate-700 dark:text-slate-300',
    border: 'border-slate-200 dark:border-slate-700',
    label: 'Dinheiro',
  },
  FGTS: {
    dot: 'bg-lime-500',
    bg: 'bg-lime-100 dark:bg-lime-900/30',
    text: 'text-lime-700 dark:text-lime-300',
    border: 'border-lime-200 dark:border-lime-800',
    label: 'FGTS',
  },
  PRIVATE_PENSION: {
    dot: 'bg-cyan-500',
    bg: 'bg-cyan-100 dark:bg-cyan-900/30',
    text: 'text-cyan-700 dark:text-cyan-300',
    border: 'border-cyan-200 dark:border-cyan-800',
    label: 'Previdência',
  },
  // Legacy aliases — TODO(spec-09): remove
  STOCK_BR: {
    dot: 'bg-blue-500',
    bg: 'bg-blue-100 dark:bg-blue-900/30',
    text: 'text-blue-700 dark:text-blue-300',
    border: 'border-blue-200 dark:border-blue-800',
    label: 'Ação BR',
  },
  STOCK_US: {
    dot: 'bg-blue-500',
    bg: 'bg-blue-100 dark:bg-blue-900/30',
    text: 'text-blue-700 dark:text-blue-300',
    border: 'border-blue-200 dark:border-blue-800',
    label: 'Ação US',
  },
  FII: {
    dot: 'bg-emerald-500',
    bg: 'bg-emerald-100 dark:bg-emerald-900/30',
    text: 'text-emerald-700 dark:text-emerald-300',
    border: 'border-emerald-200 dark:border-emerald-800',
    label: 'FII',
  },
  BOND: {
    dot: 'bg-amber-500',
    bg: 'bg-amber-100 dark:bg-amber-900/30',
    text: 'text-amber-700 dark:text-amber-300',
    border: 'border-amber-200 dark:border-amber-800',
    label: 'Bond',
  },
}

export interface CurrencyToken {
  bg: string
  text: string
  border: string
}

export const CURRENCY_PILL: Record<'BRL' | 'USD', CurrencyToken> = {
  BRL: {
    bg: 'bg-amber-50 dark:bg-amber-900/20',
    text: 'text-amber-700 dark:text-amber-300',
    border: 'border-amber-200 dark:border-amber-800',
  },
  USD: {
    bg: 'bg-emerald-50 dark:bg-emerald-900/20',
    text: 'text-emerald-700 dark:text-emerald-300',
    border: 'border-emerald-200 dark:border-emerald-800',
  },
}
