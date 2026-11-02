/* Spec 71 — "Importar arquivo" a partir de Movimentações: escolhe a conta
 * corrente ou o cartão e segue o mesmo fluxo das páginas da conta/cartão
 * (upload → job → BankImportReviewModal). Nenhuma lógica nova de backend.
 *
 * O <input type=file> fica dentro do modal: o clique em "Escolher arquivo"
 * é o gesto do usuário (o browser bloqueia abrir o seletor por código
 * depois de um setState).
 */
import { useState } from 'react'
import { X } from 'lucide-react'

import type { AccountOut, BankImportResult, CategoryOut, CreditCardOut } from '../lib/api'
import { useBankImport } from '../lib/bankImport'
import { useEscapeKey } from '../lib/useEscapeKey'
import { ImportButton } from './BankImport'
import BankImportReviewModal from './BankImportReviewModal'

export default function ImportFileModal({ accounts, cards, categories, onApplied, onError, onClose }: {
  accounts: AccountOut[]
  cards: CreditCardOut[]
  categories: CategoryOut[]
  onApplied: (result: BankImportResult) => void
  onError: (message: string) => void
  onClose: () => void
}) {
  const checking = accounts.filter(a => a.account_type === 'checking' && a.is_active)
  const activeCards = cards.filter(c => c.is_active)
  const first = checking[0] ? `account:${checking[0].id}` : activeCards[0] ? `card:${activeCards[0].id}` : ''
  const [target, setTarget] = useState(first)
  const [kind, id] = target ? (target.split(':') as ['account' | 'card', string]) : ['account' as const, undefined]
  const imports = useBankImport(kind, id, onError)

  // Picker fecha com ESC — mas não no meio do upload/extração.
  useEscapeKey(() => { if (!imports.reviewing && !imports.importing) onClose() })

  if (imports.reviewing) {
    return (
      <BankImportReviewModal
        job={imports.reviewing} accounts={accounts} categories={categories}
        onApplied={result => { imports.setReviewing(null); onApplied(result) }}
        onClose={() => { imports.setReviewing(null); onClose() }}
      />
    )
  }

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/40">
      <div role="dialog" aria-label="Importar arquivo"
        className="w-full max-w-sm bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-700 shadow-xl p-6">
        <div className="flex items-start justify-between mb-3">
          <h2 className="text-base font-semibold text-gray-900 dark:text-white">Para qual conta ou cartão?</h2>
          <button onClick={() => { if (!imports.importing) onClose() }} disabled={imports.importing} aria-label="Fechar"
            className="w-7 h-7 inline-flex items-center justify-center rounded-md text-gray-400 hover:text-gray-700 dark:hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800 disabled:opacity-50">
            <X className="w-4 h-4" />
          </button>
        </div>
        {!first ? (
          <p className="text-sm text-gray-500">Nenhuma conta corrente ou cartão ativo.</p>
        ) : (
          <div className="space-y-2 max-h-72 overflow-y-auto" role="radiogroup" aria-label="Conta ou cartão">
            {checking.length > 0 && <div className="text-[10px] uppercase tracking-wider text-gray-500">Contas</div>}
            {checking.map(a => (
              <label key={a.id} className="flex items-center gap-2 text-[13px] text-gray-900 dark:text-white cursor-pointer">
                <input type="radio" name="import-target" value={`account:${a.id}`} checked={target === `account:${a.id}`}
                  disabled={imports.importing} onChange={e => setTarget(e.target.value)} />
                {a.name} <span className="text-[11px] text-gray-500">{a.currency}</span>
              </label>
            ))}
            {activeCards.length > 0 && <div className="text-[10px] uppercase tracking-wider text-gray-500 pt-1">Cartões</div>}
            {activeCards.map(c => (
              <label key={c.id} className="flex items-center gap-2 text-[13px] text-gray-900 dark:text-white cursor-pointer">
                <input type="radio" name="import-target" value={`card:${c.id}`} checked={target === `card:${c.id}`}
                  disabled={imports.importing} onChange={e => setTarget(e.target.value)} />
                {c.name}
              </label>
            ))}
          </div>
        )}
        <div className="flex justify-end gap-3 mt-5">
          <button onClick={onClose} disabled={imports.importing}
            className="px-4 py-2 rounded-lg text-sm text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 disabled:opacity-50">
            Cancelar
          </button>
          {first && (
            <ImportButton label={kind === 'card' ? 'Escolher fatura' : 'Escolher extrato'} importing={imports.importing}
              inputRef={imports.inputRef} onPick={imports.onPick} />
          )}
        </div>
      </div>
    </div>
  )
}
