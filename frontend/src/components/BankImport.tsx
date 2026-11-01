/* Spec 71 — upload do extrato (conta corrente) / fatura (cartão) + histórico
 * de imports da fonte. Compartilhado por AccountDetail e CreditCardDetail.
 *
 * Upload → job (o LLM roda inline: 1–3 min, proxy em 600 s) com spinner no
 * botão; EXTRACTED abre a revisão; FAILED / 409 (arquivo já importado) vão
 * pro toast da página. O histórico lista cada arquivo com período, status e
 * "ver N movimentações" (lista filtrada pelo job).
 */
import { Link } from 'react-router-dom'
import { FileText, Loader2 } from 'lucide-react'

import type { StatementImportOut } from '../lib/api'
import { IMPORT_ACCEPT } from '../lib/bankImport'
import { Card, SectionTitle } from './ui'
import SourceFileClip from './SourceFileClip'

const STATUS_LABEL: Record<string, { label: string; cls: string }> = {
  CONFIRMED: { label: 'Importado', cls: 'text-emerald-600 dark:text-emerald-400' },
  EXTRACTED: { label: 'Aguardando revisão', cls: 'text-amber-600 dark:text-amber-400' },
  FAILED: { label: 'Falhou', cls: 'text-red-600 dark:text-red-400' },
  REJECTED: { label: 'Descartado', cls: 'text-gray-500' },
  RUNNING: { label: 'Extraindo', cls: 'text-gray-500' },
  PENDING: { label: 'Extraindo', cls: 'text-gray-500' },
}

function fmtDay(iso: string | null) {
  if (!iso) return '—'
  const [y, m, d] = iso.split('-')
  return `${d}/${m}/${y.slice(2)}`
}

export function ImportButton({ label, importing, inputRef, onPick }: {
  label: string
  importing: boolean
  inputRef: React.RefObject<HTMLInputElement | null>
  onPick: (e: React.ChangeEvent<HTMLInputElement>) => void
}) {
  return (
    <>
      <input ref={inputRef} type="file" accept={IMPORT_ACCEPT} className="hidden" onChange={onPick}
        aria-label={`${label} — arquivo`} data-testid="import-file-input" />
      <button type="button" onClick={() => inputRef.current?.click()} disabled={importing}
        title="OFX, PDF, CSV, XLSX ou print — a leitura pode levar 1–3 min"
        className="h-8 px-3 inline-flex items-center gap-1.5 rounded-lg text-[12px] bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700 disabled:opacity-60 transition-colors">
        {importing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <FileText className="w-3.5 h-3.5" />}
        {importing ? 'Lendo arquivo…' : label}
      </button>
    </>
  )
}

export function ImportHistory({ title, history, onReview, onError }: {
  title: string
  history: StatementImportOut[]
  onReview: (job: StatementImportOut) => void
  onError: (msg: string) => void
}) {
  // Um arquivo pode ter vários jobs (falhou → retentou): mostra o mais recente.
  const latest = history.filter((j, i) => history.findIndex(x => x.attachment_id === j.attachment_id) === i)
  if (latest.length === 0) return null
  return (
    <Card>
      <SectionTitle>{title}</SectionTitle>
      <table className="w-full text-[12px]" data-testid="import-history">
        <thead>
          <tr className="text-[10px] uppercase tracking-wider text-gray-500">
            <th className="text-left font-medium px-2 py-2">Arquivo</th>
            <th className="text-left font-medium px-2 py-2">Período</th>
            <th className="text-left font-medium px-2 py-2">Status</th>
            <th className="text-right font-medium px-2 py-2">Movimentações</th>
          </tr>
        </thead>
        <tbody>
          {latest.map(j => {
            const st = STATUS_LABEL[j.status] ?? { label: j.status, cls: 'text-gray-500' }
            return (
              <tr key={j.id} className="border-t border-gray-100 dark:border-gray-800">
                <td className="px-2 py-2">
                  <div className="flex items-center gap-1.5 text-gray-900 dark:text-white">
                    <SourceFileClip attachmentId={j.attachment_id} filename={j.filename} onError={onError} />
                    <span className="truncate max-w-[260px]">{j.filename ?? 'arquivo'}</span>
                  </div>
                </td>
                <td className="px-2 tnum text-gray-500">{fmtDay(j.statement_period_start)} – {fmtDay(j.statement_period_end)}</td>
                <td className={`px-2 ${st.cls}`} title={j.error_message ?? undefined}>{st.label}</td>
                <td className="px-2 text-right">
                  {j.status === 'EXTRACTED' ? (
                    <button type="button" onClick={() => onReview(j)} className="text-indigo-500 hover:text-indigo-400">Revisar</button>
                  ) : j.transaction_count > 0 ? (
                    <Link to={`/transactions?extraction_job_id=${j.id}`} className="text-indigo-500 hover:text-indigo-400">
                      ver {j.transaction_count} {j.transaction_count === 1 ? 'movimentação' : 'movimentações'}
                    </Link>
                  ) : <span className="text-gray-400">—</span>}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </Card>
  )
}
