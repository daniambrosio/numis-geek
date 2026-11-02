/* Spec 83 — vínculo do lançamento do ativo com a movimentação que ele
 * pagou (venda → "despesa: Coinbase One") ou recebeu (compra → "receita: …"). */
import type { AssetMovementOut } from '../lib/api'

export default function LinkedTxBadge({ m }: { m: Pick<AssetMovementOut, 'id' | 'linked_transaction_id' | 'linked_transaction_description' | 'linked_transaction_amount'> }) {
  if (!m.linked_transaction_id) return null
  const income = (m.linked_transaction_amount ?? 0) > 0
  return (
    <span
      data-testid={`movement-linked-badge-${m.id}`}
      title="Movimentação vinculada — editar data/valor muda os dois lados"
      className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] bg-violet-500/10 text-violet-600 dark:text-violet-300 max-w-[200px] truncate align-middle"
    >
      {income ? 'receita' : 'despesa'}: {m.linked_transaction_description}
    </span>
  )
}
