/* Regras de formulário de ativo compartilhadas entre AssetModal (criação e
 * details de renda fixa / físico) e AssetDataCard (edição inline na página
 * do ativo, spec 81). Espelham AssetRequest._validate no backend. */
import type { AccountOut, AssetClass, FixedIncomeIndexer } from './api'

export const CLASS_LABELS: Record<AssetClass, string> = {
  STOCK: 'Ação',
  REIT: 'FII / REIT',
  ETF: 'ETF',
  FIXED_INCOME: 'Renda Fixa',
  FUND: 'Fundo',
  CRYPTO: 'Cripto',
  REAL_ESTATE: 'Imóvel',
  VEHICLE: 'Veículo',
  CASH: 'Dinheiro',
  FGTS: 'FGTS',
  PRIVATE_PENSION: 'Previdência',
  OPTION: 'Opção',
}

// PRIVATE_PENSION/FGTS/CASH behave like ticker classes but ticker is optional
// (per spec 07a — Notion has no ticker for those rows).
export const TICKER_REQUIRED: AssetClass[] = ['STOCK', 'ETF', 'REIT', 'CRYPTO']
export const TICKER_FORBIDDEN: AssetClass[] = ['FIXED_INCOME', 'REAL_ESTATE', 'VEHICLE']
export const NEEDS_FIXED_INCOME: AssetClass[] = ['FIXED_INCOME']
export const NEEDS_PHYSICAL: AssetClass[] = ['REAL_ESTATE', 'VEHICLE']
/** Classes cujos `details` só se editam pelo AssetModal. */
export const NEEDS_DETAILS: AssetClass[] = [...NEEDS_FIXED_INCOME, ...NEEDS_PHYSICAL]

export const INDEXERS: FixedIncomeIndexer[] = ['CDI', 'IPCA', 'SELIC', 'PREFIXED', 'USD']

/** Spec 10 — a conta de investimento é resolvida por (workspace, FI). */
export function resolveInvestmentAccount(
  accounts: AccountOut[], fiId: string,
): AccountOut | null {
  return accounts.find(
    a => a.financial_institution_id === fiId && a.account_type === 'investment',
  ) ?? null
}
