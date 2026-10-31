/* Spec 69 — contagens do sidebar (badge de Cartões e Faturas), fiel ao proto
 * (index.html:1877-1878: badge = CARDS.length / INVOICES.length).
 *
 * Refresh triggers: page load + `cards-changed` window event (emitido ao
 * criar cartão/fatura). Mesmo padrão do useInReviewSnapshot. Erro de fetch
 * só esconde o badge — nunca redireciona.
 */
import { useEffect, useState } from 'react'

import { api } from './api'

export interface CardCounts {
  cards: number
  invoices: number
}

export const CARDS_CHANGED_EVENT = 'cards-changed'

export function useCardCounts(): CardCounts | null {
  const [counts, setCounts] = useState<CardCounts | null>(null)
  useEffect(() => {
    let cancelled = false
    function refresh() {
      Promise.all([api.listCreditCards(), api.listInvoices()])
        .then(([cards, invoices]) => {
          if (!cancelled) setCounts({ cards: cards.length, invoices: invoices.length })
        })
        .catch(() => { if (!cancelled) setCounts(null) })
    }
    refresh()
    window.addEventListener(CARDS_CHANGED_EVENT, refresh)
    return () => {
      cancelled = true
      window.removeEventListener(CARDS_CHANGED_EVENT, refresh)
    }
  }, [])
  return counts
}
