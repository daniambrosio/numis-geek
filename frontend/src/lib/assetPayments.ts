/* Spec 83 — pagar e receber com ativos: regras compartilhadas da UI. */
import type { AssetMovementOut, AssetOut } from './api'

// Mesma regra do backend (positions._COTADO_CLASSES): o resto é modo valor,
// qty=1 e o valor é o que importa.
export const COTADO_CLASSES = new Set(['STOCK', 'REIT', 'ETF', 'OPTION', 'CRYPTO'])

/** Ativos que podem pagar/receber: ativos, sem opção e sem o espelho de
 * conta corrente (esse paga pela própria conta). */
export function payableAssets(assets: AssetOut[]): AssetOut[] {
  const key = (a: AssetOut) => (a.ticker || a.name).toLocaleLowerCase('pt-BR')
  return assets
    .filter(a => a.is_active !== false && a.asset_class !== 'OPTION' && !a.linked_account_id)
    .sort((a, b) => key(a).localeCompare(key(b), 'pt-BR'))
}


export function linkedDeactivateWarning(m: Pick<AssetMovementOut, 'linked_transaction_id' | 'linked_transaction_description' | 'linked_transaction_amount'>): string | null {
  if (!m.linked_transaction_id) return null
  const kind = (m.linked_transaction_amount ?? 0) > 0 ? 'A receita' : 'A despesa'
  return `${kind} vinculada "${m.linked_transaction_description}" também será excluída de Movimentações (restaurar o lançamento não a traz de volta).`
}
