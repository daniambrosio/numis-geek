/* Spec 71 — estado do fluxo de import (extrato/fatura) + helpers puros da
 * revisão. Fica fora dos componentes (react-refresh/only-export-components). */
import { useCallback, useEffect, useRef, useState } from 'react'

import {
  api, type BankImportAction, type BankImportDecision, type BankImportResult, type BankImportRow,
  type StatementImportOut,
} from './api'

export const IMPORT_ACCEPT = '.ofx,.qfx,.csv,.xlsx,.xls,.pdf,.png,.jpg,.jpeg,.webp'

export const ACTION_LABEL: Record<BankImportAction, string> = {
  import: 'Importar',
  skip: 'Pular',
  reconcile: 'Reconciliar',
  import_anyway: 'Importar mesmo assim',
  pay: 'Pagar fatura',
  settle: 'Marcar pago',
  link: 'Vincular pagamento',
}

const CREATES: BankImportAction[] = ['import', 'import_anyway', 'settle', 'pay']

/** Decisões iniciais = default de cada linha (+ conta sugerida do pagamento). */
export function initialDecisions(rows: BankImportRow[]): Record<string, BankImportDecision> {
  const out: Record<string, BankImportDecision> = {}
  for (const r of rows) {
    out[r.row_id] = { action: r.default_action }
    if (r.scheduled) out[r.row_id].occurrence_id = r.scheduled.occurrence_id
    if (r.invoice_payment?.payment_account_id) out[r.row_id].payment_account_id = r.invoice_payment.payment_account_id
  }
  return out
}

/** "Importar N · Reconciliar M" — N = linhas que criam movimentação. */
export function countDecisions(decisions: Record<string, BankImportDecision>) {
  let toImport = 0
  let toReconcile = 0
  for (const d of Object.values(decisions)) {
    if (CREATES.includes(d.action)) toImport += 1
    else if (d.action === 'reconcile' || d.action === 'link') toReconcile += 1
  }
  return { toImport, toReconcile }
}

export function summarizeResult(r: BankImportResult | null | undefined): string {
  if (!r) return 'Import aplicado.'
  const parts = [`${r.created} importada${r.created === 1 ? '' : 's'}`, `${r.reconciled} reconciliada${r.reconciled === 1 ? '' : 's'}`]
  if (r.paid_invoices) parts.push(`${r.paid_invoices} fatura${r.paid_invoices === 1 ? '' : 's'} paga${r.paid_invoices === 1 ? '' : 's'}`)
  if (r.settled) parts.push(`${r.settled} conta${r.settled === 1 ? '' : 's'} quitada${r.settled === 1 ? '' : 's'}`)
  if (r.new_parties) parts.push(`${r.new_parties} fornecedor${r.new_parties === 1 ? '' : 'es'} novo${r.new_parties === 1 ? '' : 's'}`)
  return parts.join(' · ')
}

/** Upload → job (LLM inline, 1–3 min) → EXTRACTED abre a revisão; FAILED e
 * 409 (arquivo já importado) vão pro `onError` (toast da página). */
export function useBankImport(kind: 'account' | 'card', sourceId: string | undefined, onError: (msg: string) => void) {
  const [importing, setImporting] = useState(false)
  const [reviewing, setReviewing] = useState<StatementImportOut | null>(null)
  const [history, setHistory] = useState<StatementImportOut[]>([])
  const inputRef = useRef<HTMLInputElement>(null)

  const reloadHistory = useCallback(() => {
    if (!sourceId) return Promise.resolve()
    const p = kind === 'account' ? api.listStatementImports(sourceId) : api.listInvoiceImports(sourceId)
    // Histórico é acessório: falha aqui não derruba a página.
    return p.then(setHistory).catch(() => {})
  }, [kind, sourceId])

  useEffect(() => { void reloadHistory() }, [reloadHistory])

  async function upload(file: File) {
    if (!sourceId) return
    setImporting(true)
    try {
      const job = kind === 'account' ? await api.importStatement(sourceId, file) : await api.importInvoice(sourceId, file)
      if (job.status === 'EXTRACTED') setReviewing(job)
      else onError(`Extração falhou: ${job.error_message ?? 'erro desconhecido'}`)
    } catch (err) {
      onError(err instanceof Error ? err.message : 'Erro ao importar.')
    } finally {
      setImporting(false)
      void reloadHistory()
    }
  }

  function onPick(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0]
    e.target.value = ''
    if (f) void upload(f)
  }

  return { importing, reviewing, setReviewing, history, reloadHistory, inputRef, onPick }
}
