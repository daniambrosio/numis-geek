/* Spec 72 — composer "Conta a pagar/receber" (menu Novo → Caixa & Cartões).
 *
 * Sem protótipo (design novo declarado na spec): reaproveita o shell e os
 * primitivos dos composers da spec 70. Uma tela só cobre as 4 frequências:
 * Avulsa (scheduled_transaction sem rule), Mensal, Anual e Parcelada (rule
 * materializada pelo backend até hoje + 90 dias).
 *
 * Valor é SEMPRE positivo — a direção (A pagar / A receber) dá o sinal.
 * Também edita uma recorrência (só ocorrências futuras pendentes mudam) ou
 * uma ocorrência isolada (descrição/valor/conta/categoria/party/notas).
 */
import { useState } from 'react'
import type {
  AccountOut, CategoryOut, PartyOut, RecurrenceFrequency, RecurrenceRuleOut,
  RecurrenceRulePayload, ScheduledCreatePayload, ScheduledDirection, ScheduledTransactionOut,
  ScheduledUpdatePayload,
} from '../lib/api'
import { parseDecimal } from '../lib/parseDecimal'
import { todayISO } from '../lib/format'
import {
  CategorySelect, ComposerShell, Field, Preview, PreviewLine, fmtMoney, inputCls,
} from './TransactionComposers'

export type FrequencyChoice = 'ONE_OFF' | RecurrenceFrequency

export const FREQUENCY_LABELS: Record<FrequencyChoice, string> = {
  ONE_OFF: 'Avulsa',
  MONTHLY: 'Mensal',
  YEARLY: 'Anual',
  INSTALLMENT: 'Parcelada',
}

export const MONTH_LABELS = ['Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho', 'Julho', 'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro']

function isoOf(y: number, m: number, d: number): string {
  return `${y}-${String(m).padStart(2, '0')}-${String(d).padStart(2, '0')}`
}

/** Próximos vencimentos de uma recorrência — espelha `slot_dates` +
 * `materialize_rule` do backend (dia 1–28, então nunca precisa de clamp).
 *
 * - criação: todos os slots desde o início (o backend cria os passados como
 *   em atraso), parcela k = já pagas + índice + 1;
 * - edição (`notBefore` = hoje, `heldSlotDates`/`heldInstallments` = o que a
 *   edição mantém, vindos do backend): o backend apaga as futuras pendentes e
 *   recria só slots >= hoje, pulando mês (anual: ano) que já tem ocorrência
 *   mantida; as parcelas recebem, em ordem, os números que ninguém mantém —
 *   a numeração continua da primeira parcela livre (audit 2026-10-31). */
export function previewDueDates(opts: {
  frequency: RecurrenceFrequency
  day: number
  month?: number | null
  start: string
  end?: string | null
  installmentTotal?: number | null
  installmentPaid?: number | null
  notBefore?: string | null
  heldSlotDates?: string[]
  heldInstallments?: number[]
}, n = 3): { date: string; k: number | null }[] {
  const { frequency, day, start } = opts
  if (!start || !(day >= 1 && day <= 28)) return []
  if (frequency === 'YEARLY' && !opts.month) return []
  const [sy, sm] = start.split('-').map(Number)
  const out: { date: string; k: number | null }[] = []
  const end = opts.end || null
  const yearly = frequency === 'YEARLY'
  const period = (iso: string) => (yearly ? iso.slice(0, 4) : iso.slice(0, 7))
  const held = new Set(opts.heldSlotDates ?? [])
  const heldPeriods = new Set([...held].map(period))
  let free: number[] = []
  if (frequency === 'INSTALLMENT') {
    if (!opts.installmentTotal) return []
    const taken = new Set(opts.heldInstallments ?? [])
    for (let k = (opts.installmentPaid ?? 0) + 1; k <= opts.installmentTotal; k++) if (!taken.has(k)) free.push(k)
  }
  let y = sy
  let m = yearly ? opts.month! : sm
  if (isoOf(y, m, day) < start) {
    if (yearly) y += 1
    else { m += 1; if (m > 12) { m = 1; y += 1 } }
  }
  // guarda contra laço infinito (fim/limite sempre param antes na prática)
  for (let guard = 0; out.length < n && guard < 2400; guard++) {
    const d = isoOf(y, m, day)
    if (end && d > end) break
    if (frequency === 'INSTALLMENT' && free.length === 0) break
    const skip = (opts.notBefore && d < opts.notBefore) || held.has(d) || heldPeriods.has(period(d))
    if (!skip) {
      if (frequency === 'INSTALLMENT') {
        out.push({ date: d, k: free[0] })
        free = free.slice(1)
      } else {
        out.push({ date: d, k: null })
      }
    }
    if (yearly) y += 1
    else { m += 1; if (m > 12) { m = 1; y += 1 } }
  }
  return out
}

function fmtDate(iso: string) {
  const [y, m, d] = iso.split('-')
  return `${d}/${m}/${y}`
}

export type ScheduledComposerMode =
  | { kind: 'new'; frequency?: FrequencyChoice }
  | { kind: 'rule'; rule: RecurrenceRuleOut }
  | { kind: 'occurrence'; occ: ScheduledTransactionOut }

export default function ScheduledComposer({
  mode, accounts, categories, parties, onCreateOneOff, onCreateRule, onUpdateRule, onUpdateOccurrence, onClose,
}: {
  mode: ScheduledComposerMode
  accounts: AccountOut[]
  categories: CategoryOut[]
  parties: PartyOut[]
  onCreateOneOff: (data: ScheduledCreatePayload) => Promise<unknown>
  onCreateRule: (data: RecurrenceRulePayload) => Promise<unknown>
  onUpdateRule: (id: string, data: RecurrenceRulePayload) => Promise<unknown>
  onUpdateOccurrence: (id: string, data: ScheduledUpdatePayload) => Promise<unknown>
  onClose: () => void
}) {
  const rule = mode.kind === 'rule' ? mode.rule : undefined
  const occ = mode.kind === 'occurrence' ? mode.occ : undefined
  const src = rule ?? occ
  const checkings = accounts.filter(a => a.account_type === 'checking' && (a.is_active || a.id === src?.expected_account_id))
  const activeParties = parties.filter(p => p.is_active)
  // Party já gravado mas inativo (ou fora da lista, que só traz ativos):
  // aparece pelo nome, marcado "(inativa)", e pode ser limpo.
  const savedParty = src?.party_id ? parties.find(p => p.id === src.party_id) : undefined
  const inactiveParty = src?.party_id && !(savedParty && savedParty.is_active)
    ? { id: src.party_id, name: savedParty?.name ?? src.party_name ?? 'Fornecedor/cliente' }
    : null

  const [direction, setDirection] = useState<ScheduledDirection>(src?.direction ?? 'PAYABLE')
  const [frequency, setFrequency] = useState<FrequencyChoice>(
    rule ? rule.frequency : mode.kind === 'new' ? (mode.frequency ?? 'ONE_OFF') : 'ONE_OFF',
  )
  const [desc, setDesc] = useState(src?.description ?? '')
  const [amount, setAmount] = useState(src ? String(src.amount).replace('.', ',') : '')
  const [accountId, setAccountId] = useState(src?.expected_account_id ?? '')
  const [currencyState, setCurrency] = useState<'BRL' | 'USD'>(src?.currency ?? 'BRL')
  const [catId, setCatId] = useState(src?.category_id ?? '')
  const [partyId, setPartyId] = useState(src?.party_id ?? '')
  const [notes, setNotes] = useState(src?.notes ?? '')
  const [dueDate, setDueDate] = useState(todayISO())
  const [day, setDay] = useState(String(rule?.day_of_month ?? Math.min(new Date().getDate(), 28)))
  const [month, setMonth] = useState(String(rule?.month ?? new Date().getMonth() + 1))
  const [start, setStart] = useState(rule?.start_date ?? todayISO())
  const [end, setEnd] = useState(rule?.end_date ?? '')
  const [instTotal, setInstTotal] = useState(String(rule?.installment_total ?? ''))
  const [instPaid, setInstPaid] = useState(String(rule?.installment_paid ?? '0'))
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const account = accounts.find(a => a.id === accountId)
  const currency = account?.currency ?? currencyState
  const amtN = parseDecimal(amount) ?? 0
  const dayN = parseInt(day, 10)
  const monthN = parseInt(month, 10)
  const totalN = parseInt(instTotal, 10)
  const paidN = parseInt(instPaid || '0', 10)
  const isRecurring = frequency !== 'ONE_OFF'

  // Na edição o backend só recria slots >= hoje e mantém o que já foi
  // pago/cancelado/está em atraso — a prévia segue a mesma regra.
  const preview = isRecurring ? previewDueDates({
    frequency: frequency as RecurrenceFrequency, day: dayN, month: monthN, start, end: end || null,
    installmentTotal: totalN, installmentPaid: paidN,
    ...(rule ? {
      notBefore: todayISO(),
      heldSlotDates: rule.held_slot_dates ?? [],
      heldInstallments: rule.held_installment_numbers ?? [],
    } : {}),
  }) : []

  let valid = desc.trim().length > 0 && amtN > 0
  if (mode.kind !== 'occurrence') {
    if (frequency === 'ONE_OFF') valid = valid && !!dueDate
    else {
      valid = valid && dayN >= 1 && dayN <= 28 && !!start && (!end || end >= start)
      if (frequency === 'YEARLY') valid = valid && monthN >= 1 && monthN <= 12
      if (frequency === 'INSTALLMENT') valid = valid && totalN >= 1 && paidN >= 0 && paidN < totalN
    }
  }

  const signed = direction === 'PAYABLE' ? -amtN : amtN
  const common = {
    description: desc.trim(),
    amount: amtN,
    currency: account ? undefined : currency,
    expected_account_id: accountId || null,
    category_id: catId || null,
    party_id: partyId || null,
    notes: notes.trim() || null,
  }

  async function submit() {
    setError('')
    setSaving(true)
    try {
      if (occ) {
        await onUpdateOccurrence(occ.id, common)
      } else if (frequency === 'ONE_OFF') {
        await onCreateOneOff({ ...common, direction, due_date: dueDate })
      } else {
        const payload: RecurrenceRulePayload = {
          ...common,
          direction,
          frequency,
          day_of_month: dayN,
          month: frequency === 'YEARLY' ? monthN : null,
          installment_total: frequency === 'INSTALLMENT' ? totalN : null,
          installment_paid: frequency === 'INSTALLMENT' ? paidN : null,
          start_date: start,
          end_date: end || null,
        }
        if (rule) await onUpdateRule(rule.id, payload)
        else await onCreateRule(payload)
      }
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Erro ao salvar.')
    } finally {
      setSaving(false)
    }
  }

  const title = occ ? 'Editar conta' : rule ? 'Editar recorrência' : 'Nova conta a pagar/receber'
  const subtitle = occ
    ? `Só esta ocorrência · vence ${fmtDate(occ.due_date)}`
    : rule
      ? 'Altera só as ocorrências futuras ainda pendentes — pagas, canceladas e em atraso ficam como estão'
      : 'Obrigação ou direito futuro: avulsa, mensal, anual ou parcelada'
  const freqOptions: FrequencyChoice[] = rule ? ['MONTHLY', 'YEARLY', 'INSTALLMENT'] : ['ONE_OFF', 'MONTHLY', 'YEARLY', 'INSTALLMENT']

  return (
    <ComposerShell
      formId="scheduled-form" title={title} subtitle={subtitle}
      onClose={onClose} onSubmit={submit} valid={valid} saving={saving}
      saveLabel={src ? 'Salvar alterações' : 'Salvar'}
    >
      {!occ && (
        <div className="flex items-start gap-6 flex-wrap">
          <Field label="Direção">
            <div className="inline-flex items-center rounded-lg p-0.5 bg-gray-100 dark:bg-gray-800">
              {(['PAYABLE', 'RECEIVABLE'] as const).map(d => (
                <button key={d} type="button" onClick={() => setDirection(d)}
                  className={`px-3 h-8 text-[12px] font-medium rounded-md transition-colors ${
                    direction === d
                      ? d === 'PAYABLE' ? 'bg-red-500/15 text-red-600 dark:text-red-400' : 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400'
                      : 'text-gray-500'}`}>
                  {d === 'PAYABLE' ? 'A pagar' : 'A receber'}
                </button>
              ))}
            </div>
          </Field>
          <Field label="Frequência">
            <div className="inline-flex items-center rounded-lg p-0.5 bg-gray-100 dark:bg-gray-800">
              {freqOptions.map(f => (
                <button key={f} type="button" onClick={() => setFrequency(f)}
                  className={`px-3 h-8 text-[12px] font-medium rounded-md transition-colors ${
                    frequency === f ? 'bg-white dark:bg-gray-700 text-gray-900 dark:text-white shadow-sm' : 'text-gray-500'}`}>
                  {FREQUENCY_LABELS[f]}
                </button>
              ))}
            </div>
          </Field>
        </div>
      )}

      <div className="grid grid-cols-2 gap-4">
        <Field label="Descrição" span2>
          <input value={desc} onChange={e => setDesc(e.target.value)} aria-label="Descrição"
            placeholder="ex: Aluguel · Salário consultoria X · IPVA" className={inputCls} />
        </Field>
        <Field label={`Valor · ${currency}`} hint="positivo · sinal vem da direção">
          <input value={amount} onChange={e => setAmount(e.target.value)} aria-label="Valor"
            placeholder="ex: 2.500,00" className={`${inputCls} tnum`} />
        </Field>
        <Field label="Conta prevista" hint="opcional">
          <select value={accountId} onChange={e => setAccountId(e.target.value)} className={inputCls} aria-label="Conta prevista">
            <option value="">Sem conta definida</option>
            {checkings.map(a => <option key={a.id} value={a.id}>{a.name} · {a.currency}{a.is_active ? '' : ' (inativa)'}</option>)}
          </select>
        </Field>
        {!account && (
          <Field label="Moeda">
            <select value={currencyState} onChange={e => setCurrency(e.target.value as 'BRL' | 'USD')} className={inputCls} aria-label="Moeda">
              <option value="BRL">BRL</option>
              <option value="USD">USD</option>
            </select>
          </Field>
        )}
        <Field label="Categoria">
          <CategorySelect categories={categories} value={catId} onChange={setCatId}
            currentName={catId && catId === src?.category_id ? src.category_name : null} />
        </Field>
        <Field label="Fornecedor/Cliente">
          <select value={partyId} onChange={e => setPartyId(e.target.value)} className={inputCls} aria-label="Fornecedor/Cliente">
            <option value="">—</option>
            {inactiveParty && <option value={inactiveParty.id}>{inactiveParty.name} (inativa)</option>}
            {activeParties.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        </Field>

        {!occ && frequency === 'ONE_OFF' && (
          <Field label="Vencimento">
            <input type="date" value={dueDate} onChange={e => setDueDate(e.target.value)} className={inputCls} aria-label="Vencimento" />
          </Field>
        )}
        {!occ && isRecurring && (
          <>
            <Field label="Dia do vencimento" hint="1–28">
              <input type="number" min={1} max={28} value={day} onChange={e => setDay(e.target.value)} className={`${inputCls} tnum`} aria-label="Dia do vencimento" />
            </Field>
            {frequency === 'YEARLY' && (
              <Field label="Mês">
                <select value={month} onChange={e => setMonth(e.target.value)} className={inputCls} aria-label="Mês">
                  {MONTH_LABELS.map((l, i) => <option key={l} value={i + 1}>{l}</option>)}
                </select>
              </Field>
            )}
            {frequency === 'INSTALLMENT' && (
              <>
                <Field label="Nº de parcelas">
                  <input type="number" min={1} value={instTotal} onChange={e => setInstTotal(e.target.value)} className={`${inputCls} tnum`} aria-label="Nº de parcelas" placeholder="ex: 180" />
                </Field>
                <Field label="Parcelas já pagas" hint="antes do cadastro">
                  <input type="number" min={0} value={instPaid} onChange={e => setInstPaid(e.target.value)} className={`${inputCls} tnum`} aria-label="Parcelas já pagas" />
                </Field>
              </>
            )}
            <Field label={frequency === 'INSTALLMENT' ? 'Próxima parcela a partir de' : 'Início'}>
              <input type="date" value={start} onChange={e => setStart(e.target.value)} className={inputCls} aria-label="Início" />
            </Field>
            <Field label="Fim" hint="opcional">
              <input type="date" value={end} onChange={e => setEnd(e.target.value)} className={inputCls} aria-label="Fim" />
            </Field>
          </>
        )}
      </div>

      {amtN > 0 && (
        <Preview>
          <div className="flex items-center justify-between">
            <span className="text-[12px] text-gray-500 dark:text-gray-400">{direction === 'PAYABLE' ? 'A pagar' : 'A receber'}</span>
            <span className={`tnum text-base font-semibold ${signed < 0 ? 'text-red-500 dark:text-red-400' : 'text-emerald-500 dark:text-emerald-400'}`} data-testid="scheduled-preview-amount">
              {fmtMoney(signed, currency, { sign: true })}
            </span>
          </div>
          {!occ && frequency === 'ONE_OFF' && dueDate && <PreviewLine label="Vence">{fmtDate(dueDate)}</PreviewLine>}
          {preview.length > 0 && (
            <PreviewLine label="Próximos vencimentos">
              <span data-testid="scheduled-preview-dates">
                {preview.map(p => p.k ? `${fmtDate(p.date)} (${p.k}/${totalN})` : fmtDate(p.date)).join(' · ')}
              </span>
            </PreviewLine>
          )}
          {isRecurring && !occ && <PreviewLine label="Materialização">até hoje + 90 dias · o resto entra sozinho</PreviewLine>}
        </Preview>
      )}

      <Field label="Notas">
        <textarea value={notes} onChange={e => setNotes(e.target.value)} rows={2} aria-label="Notas"
          className={`${inputCls} h-auto py-2`} placeholder="ex: contrato, reajuste anual…" />
      </Field>
      {error && <p className="text-[12px] text-red-600 dark:text-red-400" role="alert">{error}</p>}
    </ComposerShell>
  )
}
