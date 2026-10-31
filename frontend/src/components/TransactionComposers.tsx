/* Spec 70 — composers do lado Caixa & Cartões, fiéis ao proto
 * (index.html:6291-6530 — TransactionComposer / CardTxComposer).
 *
 * Deltas declarados na spec 70:
 * - Cartão: o campo livre "Parcela · 1/3" vira gerador "N parcelas"
 *   (+ "a partir da fatura"), que cria 1 tx por fatura.
 * - Cartão internacional: cotação do cartão editável (o proto mostrava a
 *   PTAX desabilitada); vira fx STATEMENT.
 * - Transferência entre contas próprias: composer novo (não existe no proto).
 * - Sem sugestão de categoria por descrição (auto-categorização é spec futura).
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { Loader2, Sparkles, X } from 'lucide-react'
import {
  type AccountOut, type CategoryOut, type CreditCardOut, type InvoiceOut,
  type TransactionCreatePayload, type TransactionOut, type TransactionUpdatePayload,
  type TransferPayload,
} from '../lib/api'
import { parseDecimal } from '../lib/parseDecimal'
import { useEscapeKey } from '../lib/useEscapeKey'
import { groupCategories } from '../pages/Registry'
import { ToggleSwitch } from './ui'
import NotesAttachmentsField, {
  type AttachmentDraft, type PersistedAttachment,
} from './NotesAttachmentsField'
import { todayISO } from '../lib/format'
import { AttachmentUploadError } from '../lib/useTransactionAttachments'

const num = (s: string): number => parseDecimal(s) ?? 0
const today = () => todayISO()

export function fmtMoney(n: number, ccy: 'BRL' | 'USD', opts: { sign?: boolean } = {}) {
  const sign = opts.sign && n > 0 ? '+ ' : opts.sign && n < 0 ? '− ' : ''
  return sign + Math.abs(n).toLocaleString('pt-BR', { style: 'currency', currency: ccy })
}

/* ── shared attachment plumbing ──────────────────────────────────────── */

export interface AttachmentProps {
  persistedAttachments?: PersistedAttachment[]
  onUploadDrafts?: (entityId: string, drafts: AttachmentDraft[]) => Promise<void>
  onRemovePersistedAttachment?: (attachmentId: string) => Promise<void>
}

/* ── shell ───────────────────────────────────────────────────────────── */

function ComposerShell({
  formId, title, subtitle, onClose, onSubmit, valid, saving, saveLabel, children,
}: {
  formId: string
  title: string
  subtitle: string
  onClose: () => void
  onSubmit: () => void
  valid: boolean
  saving: boolean
  saveLabel: string
  children: React.ReactNode
}) {
  const wrapperRef = useRef<HTMLDivElement>(null)
  useEffect(() => { wrapperRef.current?.focus() }, [])
  useEscapeKey(onClose)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
        (document.getElementById(formId) as HTMLFormElement | null)?.requestSubmit()
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [formId])

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
      <div
        ref={wrapperRef}
        tabIndex={-1}
        role="dialog"
        aria-label={title}
        className="w-full max-w-2xl max-h-[90vh] bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-800 shadow-2xl flex flex-col outline-none"
      >
        <div className="px-6 py-4 border-b border-gray-100 dark:border-gray-800 flex items-start justify-between">
          <div>
            <h2 className="text-base font-semibold text-gray-900 dark:text-white">{title}</h2>
            <p className="text-[12px] text-gray-500 dark:text-gray-400 mt-0.5">{subtitle}</p>
          </div>
          <button type="button" onClick={onClose} title="Fechar (Esc)"
            className="w-7 h-7 inline-flex items-center justify-center rounded-md text-gray-400 hover:text-gray-700 dark:hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors">
            <X className="w-4 h-4" />
          </button>
        </div>
        <form
          id={formId}
          onSubmit={e => { e.preventDefault(); if (valid && !saving) onSubmit() }}
          className="px-6 py-5 overflow-y-auto flex-1 scrollbar-thin space-y-5"
        >
          {children}
        </form>
        <div className="px-6 py-3 border-t border-gray-100 dark:border-gray-800 flex items-center justify-between">
          <span className="text-[11px] text-gray-500">
            <kbd className="px-1.5 py-0.5 mx-0.5 rounded bg-gray-100 dark:bg-gray-800 text-[10px] font-mono">⌘↵</kbd> salvar
            {' · '}
            <kbd className="px-1.5 py-0.5 mx-0.5 rounded bg-gray-100 dark:bg-gray-800 text-[10px] font-mono">esc</kbd> fechar
          </span>
          <div className="flex gap-2">
            <button type="button" onClick={onClose}
              className="h-8 px-3 inline-flex items-center rounded-md text-[12px] text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors">
              Cancelar
            </button>
            <button type="submit" form={formId} disabled={!valid || saving}
              className="h-8 px-3 inline-flex items-center gap-1.5 rounded-md bg-indigo-500 hover:bg-indigo-400 text-white text-[12px] font-medium disabled:opacity-50 disabled:cursor-not-allowed transition-colors">
              {saving ? <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Salvando…</> : `✓ ${saveLabel}`}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

/* ── primitives ──────────────────────────────────────────────────────── */

function Field({ label, hint, span2, children }: { label: string; hint?: string; span2?: boolean; children: React.ReactNode }) {
  return (
    <div className={span2 ? 'col-span-2' : undefined}>
      <div className="flex items-baseline justify-between mb-1.5">
        <span className="block text-[10px] uppercase tracking-wider font-semibold text-gray-500 dark:text-gray-400">{label}</span>
        {hint && <span className="text-[10px] text-gray-400 dark:text-gray-600">· {hint}</span>}
      </div>
      {children}
    </div>
  )
}

const inputCls =
  'w-full h-9 px-3 text-[13px] rounded-md bg-gray-50 dark:bg-gray-800/50 border border-gray-200 dark:border-gray-800 text-gray-900 dark:text-white placeholder:text-gray-400 dark:placeholder:text-gray-600 focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 disabled:opacity-60'

function Preview({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-lg bg-indigo-500/5 border border-indigo-500/20 p-3.5 space-y-2">
      <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider font-semibold text-indigo-500 dark:text-indigo-400">
        <Sparkles className="w-3 h-3" /> Pré-visualização
      </div>
      {children}
    </div>
  )
}

function PreviewLine({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between text-[12px]">
      <span className="text-gray-500 dark:text-gray-400">{label}</span>
      <span className="text-gray-700 dark:text-gray-300">{children}</span>
    </div>
  )
}

/** Subcategorias agrupadas pela raiz (tx só aponta pra sub — spec 68 v2). */
export function CategorySelect({
  categories, value, onChange, filterKind,
}: {
  categories: CategoryOut[]
  value: string
  onChange: (v: string) => void
  filterKind?: CategoryOut['kind']
}) {
  const grouped = useMemo(() => groupCategories(categories.filter(c => c.is_active)), [categories])
  return (
    <select value={value} onChange={e => onChange(e.target.value)} className={inputCls} aria-label="Categoria">
      <option value="">Sem categoria</option>
      {grouped.map(({ root, children }) => {
        const subs = filterKind ? children.filter(c => c.kind === filterKind) : children
        if (!subs.length) return null
        return (
          <optgroup key={root.id} label={root.name}>
            {subs.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
          </optgroup>
        )
      })}
    </select>
  )
}

function CategoryDot({ categories, id }: { categories: CategoryOut[]; id: string }) {
  const c = categories.find(x => x.id === id)
  if (!c) return null
  const parent = categories.find(x => x.id === c.parent_id)
  const color = c.color ?? parent?.color ?? '#6b7280'
  return (
    <span className="inline-flex items-center gap-1">
      <span className="w-1.5 h-1.5 rounded-full" style={{ background: color }} />
      {parent ? `${parent.name} · ` : ''}{c.name}
    </span>
  )
}

/** Sobe os anexos depois do write. Falhou → mantém só os rascunhos que
 * falharam e devolve false; o composer guarda a tx salva (`savedTx`) e o
 * próximo "Salvar" só re-tenta os anexos — nunca cria a tx de novo (o
 * fingerprint não é único: 2º create duplicava a compra e as parcelas). */
async function uploadAfterSave(
  saved: TransactionOut | undefined,
  drafts: AttachmentDraft[],
  onUploadDrafts: AttachmentProps['onUploadDrafts'],
  setDrafts: (d: AttachmentDraft[]) => void,
  setWarning: (s: string) => void,
): Promise<boolean> {
  if (!saved || !drafts.length || !onUploadDrafts) return true
  try {
    await onUploadDrafts(saved.id, drafts)
    return true
  } catch (err) {
    if (err instanceof AttachmentUploadError) setDrafts(err.failed)
    setWarning(
      `Lançamento salvo, mas alguns anexos falharam: ${err instanceof Error ? err.message : 'erro'}. `
      + 'Salvar de novo só re-envia os anexos; fechar mantém o lançamento sem eles.',
    )
    return false
  }
}

/* ── Movimentação (conta corrente) ───────────────────────────────────── */

export function TransactionComposer({
  accounts, categories, initial, onCreate, onUpdate, onClose,
  persistedAttachments, onUploadDrafts, onRemovePersistedAttachment,
}: {
  accounts: AccountOut[]
  categories: CategoryOut[]
  initial?: TransactionOut
  onCreate: (data: TransactionCreatePayload) => Promise<TransactionOut[]>
  onUpdate: (id: string, data: TransactionUpdatePayload) => Promise<TransactionOut[]>
  onClose: () => void
} & AttachmentProps) {
  const checkings = accounts.filter(a => a.account_type === 'checking' && a.is_active)
  const [accIdState, setAccId] = useState(initial?.checking_account_id ?? '')
  // Vazio = a 1ª opção visível no select (listas podem chegar depois do mount).
  const accId = accIdState || checkings[0]?.id || ''
  const [date, setDate] = useState(initial?.event_date ?? today())
  const [direction, setDirection] = useState<'in' | 'out'>(initial && initial.amount > 0 ? 'in' : 'out')
  const [amount, setAmount] = useState(initial ? String(Math.abs(initial.amount)).replace('.', ',') : '')
  const [desc, setDesc] = useState(initial?.description ?? '')
  const [catId, setCatId] = useState(initial?.category_id ?? '')
  const [notes, setNotes] = useState(initial?.notes ?? '')
  const [drafts, setDrafts] = useState<AttachmentDraft[]>([])
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [warning, setWarning] = useState('')
  // Write já feito, faltam anexos — "Salvar" passa a só re-tentar o upload.
  const [savedTx, setSavedTx] = useState<TransactionOut | null>(null)

  const acc = accounts.find(a => a.id === accId)
  const ccy = acc?.currency ?? 'BRL'
  const amtN = num(amount)
  const signed = direction === 'in' ? amtN : -amtN
  // Pernas de transferência e pagamento de fatura têm valor travado (409 no backend).
  const amountLocked = !!initial && (!!initial.transfer_group_id || !!initial.paid_invoice_id)
  const valid = !!acc && amtN > 0 && desc.trim().length > 0

  async function submit() {
    setError('')
    setSaving(true)
    try {
      let saved: TransactionOut | undefined = savedTx ?? undefined
      if (!saved && initial) {
        const changes: TransactionUpdatePayload = {
          description: desc.trim(), category_id: catId || null,
          notes: notes.trim() || null,
        }
        if (date !== initial.event_date) changes.event_date = date
        if (!amountLocked) changes.amount = signed
        saved = (await onUpdate(initial.id, changes)).find(t => t.id === initial.id)
      } else if (!saved) {
        saved = (await onCreate({
          source_type: 'CHECKING', checking_account_id: accId, event_date: date,
          description: desc.trim(), amount: signed, category_id: catId || null,
          notes: notes.trim() || null,
        }))[0]
      }
      if (saved) setSavedTx(saved)
      if (await uploadAfterSave(saved, drafts, onUploadDrafts, setDrafts, setWarning)) onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Erro ao salvar.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <ComposerShell
      formId="transaction-form"
      title={initial ? 'Editar Movimentação' : 'Nova Movimentação'}
      subtitle={initial ? 'Atualiza a movimentação de caixa' : 'Cash flow em conta corrente'}
      onClose={onClose} onSubmit={submit} valid={valid || !!savedTx} saving={saving}
      saveLabel={savedTx ? 'Enviar anexos de novo' : initial ? 'Salvar alterações' : 'Salvar'}
    >
      <Field label="Direção">
        <div className="inline-flex items-center rounded-lg p-0.5 bg-gray-100 dark:bg-gray-800">
          {(['out', 'in'] as const).map(d => (
            <button key={d} type="button" disabled={amountLocked} onClick={() => setDirection(d)}
              className={`px-3 h-8 text-[12px] font-medium rounded-md transition-colors disabled:cursor-not-allowed ${
                direction === d
                  ? d === 'out' ? 'bg-red-500/15 text-red-600 dark:text-red-400' : 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400'
                  : 'text-gray-500'}`}>
              {d === 'out' ? 'Saída · despesa' : 'Entrada · receita'}
            </button>
          ))}
        </div>
      </Field>

      <div className="grid grid-cols-2 gap-4">
        <Field label="Conta">
          <select value={accId} onChange={e => setAccId(e.target.value)} disabled={!!initial} className={inputCls} aria-label="Conta">
            {checkings.map(c => <option key={c.id} value={c.id}>{c.name} · {c.currency}</option>)}
          </select>
        </Field>
        <Field label="Data">
          <input type="date" value={date} onChange={e => setDate(e.target.value)} required className={inputCls} aria-label="Data" />
        </Field>
        <Field label="Descrição" span2>
          <input value={desc} onChange={e => setDesc(e.target.value)} aria-label="Descrição"
            placeholder="ex: Salário consultoria · ou · Mercado · Pão de Açúcar" className={inputCls} />
        </Field>
        <Field label={`Valor · ${ccy}`} hint={amountLocked ? 'travado · transferência/pagamento de fatura' : 'positivo · sinal vem do toggle'}>
          <input value={amount} onChange={e => setAmount(e.target.value)} disabled={amountLocked} aria-label="Valor"
            placeholder="ex: 612,40" className={`${inputCls} tnum`} />
        </Field>
        <Field label="Categoria">
          <CategorySelect categories={categories} value={catId} onChange={setCatId} />
        </Field>
      </div>

      {amtN > 0 && acc && (
        <Preview>
          <div className="flex items-center justify-between">
            <span className="text-[12px] text-gray-500 dark:text-gray-400">Net</span>
            <span className={`tnum text-base font-semibold ${signed < 0 ? 'text-red-500 dark:text-red-400' : 'text-emerald-500 dark:text-emerald-400'}`}>
              {fmtMoney(signed, ccy, { sign: true })}
            </span>
          </div>
          <PreviewLine label="Conta">{acc.name}</PreviewLine>
          {catId && <PreviewLine label="Categoria"><CategoryDot categories={categories} id={catId} /></PreviewLine>}
          {ccy === 'USD' && <PreviewLine label="FX">PTAX do dia · convertido no backend</PreviewLine>}
        </Preview>
      )}

      <NotesAttachmentsField
        notes={notes} onNotesChange={setNotes}
        files={drafts} onFilesChange={setDrafts}
        persisted={persistedAttachments} onRemovePersisted={onRemovePersistedAttachment}
        placeholder="ex: motivo, contexto…"
      />
      {error && <p className="text-[12px] text-red-600 dark:text-red-400">{error}</p>}
      {warning && <p className="text-[12px] text-amber-600 dark:text-amber-400">{warning}</p>}
    </ComposerShell>
  )
}

/* ── Lançamento de cartão ────────────────────────────────────────────── */

export function CardTxComposer({
  cards, categories, invoices, initial, defaultCardId, onCreate, onUpdate, onClose,
  persistedAttachments, onUploadDrafts, onRemovePersistedAttachment,
}: {
  cards: CreditCardOut[]
  categories: CategoryOut[]
  /** Faturas não pagas dos cartões — opções do "a partir da fatura". */
  invoices: InvoiceOut[]
  initial?: TransactionOut
  defaultCardId?: string
  onCreate: (data: TransactionCreatePayload) => Promise<TransactionOut[]>
  onUpdate: (id: string, data: TransactionUpdatePayload) => Promise<TransactionOut[]>
  onClose: () => void
} & AttachmentProps) {
  const active = cards.filter(c => c.is_active)
  const [cardIdState, setCardId] = useState(initial?.credit_card_account_id ?? defaultCardId ?? '')
  const cardId = cardIdState || active[0]?.id || ''
  const [date, setDate] = useState(initial?.event_date ?? today())
  const [desc, setDesc] = useState(initial?.description ?? '')
  const [amount, setAmount] = useState(initial ? String(Math.abs(initial.amount)).replace('.', ',') : '')
  const [isRefund, setIsRefund] = useState(!!initial && initial.amount > 0)
  const [usdMode, setUsdMode] = useState(false)
  const [usd, setUsd] = useState('')
  const [rate, setRate] = useState('')
  const [iof, setIof] = useState('')
  const [catId, setCatId] = useState(initial?.category_id ?? '')
  const [installments, setInstallments] = useState('1')
  const [invoiceId, setInvoiceId] = useState('')
  const [notes, setNotes] = useState(initial?.notes ?? '')
  const [drafts, setDrafts] = useState<AttachmentDraft[]>([])
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [warning, setWarning] = useState('')
  // Write já feito, faltam anexos — "Salvar" passa a só re-tentar o upload.
  const [savedTx, setSavedTx] = useState<TransactionOut | null>(null)

  const card = cards.find(c => c.id === cardId)
  const ccy = card?.currency ?? 'BRL'
  const intl = usdMode && ccy === 'BRL' && !initial
  const usdN = num(usd)
  const rateN = num(rate)
  const iofN = num(iof)
  const total = intl ? Math.round((usdN * rateN + iofN) * 100) / 100 : num(amount)
  const signed = isRefund ? total : -total
  const n = Math.max(1, Math.min(48, parseInt(installments, 10) || 1))
  const perParcel = total / n
  const cardInvoices = invoices.filter(i => i.credit_card_account_id === cardId && i.status !== 'PAID')
  const valid = !!card && total > 0 && desc.trim().length > 0 && (!intl || (usdN > 0 && rateN > 0))

  async function submit() {
    setError('')
    setSaving(true)
    try {
      let saved: TransactionOut | undefined = savedTx ?? undefined
      if (!saved && initial) {
        const changes: TransactionUpdatePayload = {
          description: desc.trim(), amount: signed,
          category_id: catId || null, notes: notes.trim() || null,
        }
        // Só manda a data quando mudou: o backend re-roteia a fatura por ela
        // e desfaria a fatura escolhida à mão no create.
        if (date !== initial.event_date) changes.event_date = date
        saved = (await onUpdate(initial.id, changes)).find(t => t.id === initial.id)
      } else if (!saved) {
        const fxNote = intl
          ? `US$ ${usdN.toLocaleString('pt-BR', { minimumFractionDigits: 2 })} @ R$ ${rateN.toLocaleString('pt-BR', { minimumFractionDigits: 4 })}`
            + (iofN > 0 ? ` + IOF ${fmtMoney(iofN, 'BRL')}` : '')
          : ''
        const rows = await onCreate({
          source_type: 'CREDIT_CARD', credit_card_account_id: cardId,
          invoice_id: invoiceId || null, event_date: date, description: desc.trim(),
          amount: signed, category_id: catId || null,
          fx_rate: intl ? rateN : null,
          notes: [fxNote, notes.trim()].filter(Boolean).join(' · ') || null,
          installments: n,
        })
        saved = rows[0]
      }
      if (saved) setSavedTx(saved)
      if (await uploadAfterSave(saved, drafts, onUploadDrafts, setDrafts, setWarning)) onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Erro ao salvar.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <ComposerShell
      formId="card-tx-form"
      title={initial ? 'Editar Lançamento de Cartão' : 'Lançamento de Cartão'}
      subtitle={initial ? 'Atualiza a compra na fatura' : 'Compra na fatura aberta'}
      onClose={onClose} onSubmit={submit} valid={valid || !!savedTx} saving={saving}
      saveLabel={savedTx ? 'Enviar anexos de novo' : initial ? 'Salvar alterações' : 'Salvar'}
    >
      <div className="grid grid-cols-2 gap-4">
        <Field label="Cartão">
          <select value={cardId} onChange={e => { setCardId(e.target.value); setInvoiceId('') }} disabled={!!initial} className={inputCls} aria-label="Cartão">
            {active.map(c => <option key={c.id} value={c.id}>{c.name}{c.last4 ? ` · ···· ${c.last4}` : ''}</option>)}
          </select>
        </Field>
        <Field label="Data">
          <input type="date" value={date} onChange={e => setDate(e.target.value)} required className={inputCls} aria-label="Data" />
        </Field>
        <Field label="Descrição" span2>
          <input value={desc} onChange={e => setDesc(e.target.value)} aria-label="Descrição"
            placeholder="ex: Restaurante Maní · ou · Apple.com" className={inputCls} />
        </Field>
        {!intl ? (
          <Field label={`Valor${n > 1 ? ' total' : ''} · ${ccy}`}>
            <input value={amount} onChange={e => setAmount(e.target.value)} aria-label="Valor"
              placeholder="ex: 284,50" className={`${inputCls} tnum`} />
          </Field>
        ) : (
          <Field label="Valor original · USD">
            <input value={usd} onChange={e => setUsd(e.target.value)} aria-label="Valor USD"
              placeholder="ex: 89,00" className={`${inputCls} tnum`} />
          </Field>
        )}
        <Field label="Categoria">
          <CategorySelect categories={categories} value={catId} onChange={setCatId} />
        </Field>
        {intl && (
          <>
            <Field label="Cotação do cartão · R$/US$">
              <input value={rate} onChange={e => setRate(e.target.value)} aria-label="Cotação"
                placeholder="ex: 5,1500" className={`${inputCls} tnum`} />
            </Field>
            <Field label="IOF · BRL" hint="opcional">
              <input value={iof} onChange={e => setIof(e.target.value)} aria-label="IOF"
                placeholder="ex: 29,40" className={`${inputCls} tnum`} />
            </Field>
          </>
        )}
        {!initial && (
          <>
            <Field label="Parcelas" hint="1 = à vista · até 48">
              <input type="number" min={1} max={48} value={installments} aria-label="Parcelas"
                onChange={e => setInstallments(e.target.value)} className={`${inputCls} tnum`} />
            </Field>
            <Field label="Fatura" hint="1ª parcela">
              <select value={invoiceId} onChange={e => setInvoiceId(e.target.value)} className={inputCls} aria-label="Fatura">
                <option value="">Pela data da compra</option>
                {cardInvoices.map(i => (
                  <option key={i.id} value={i.id}>Fecha {i.close_date.split('-').reverse().join('/')} · {i.status === 'OPEN' ? 'aberta' : 'fechada'}</option>
                ))}
              </select>
            </Field>
          </>
        )}
      </div>

      <div className="flex flex-wrap gap-4">
        {ccy === 'BRL' && !initial && (
          <ToggleSwitch on={usdMode} onChange={setUsdMode} label="Compra internacional · informar USD + IOF" />
        )}
        <ToggleSwitch on={isRefund} onChange={setIsRefund} label="Estorno · crédito na fatura" />
      </div>

      {total > 0 && card && (
        <Preview>
          <div className="flex items-center justify-between">
            <span className="text-[12px] text-gray-500 dark:text-gray-400">Lançamento na fatura</span>
            <span className={`tnum text-base font-semibold ${signed < 0 ? 'text-red-500 dark:text-red-400' : 'text-emerald-500 dark:text-emerald-400'}`}>
              {fmtMoney(signed, ccy, { sign: true })}
            </span>
          </div>
          {n > 1 && <PreviewLine label="Parcelamento">{n}x de {fmtMoney(perParcel, ccy)} · 1 por fatura</PreviewLine>}
          {intl && (
            <>
              <PreviewLine label="Valor USD">US$ {usdN.toFixed(2)} @ R$ {rateN.toFixed(4)}</PreviewLine>
              <PreviewLine label="IOF">{fmtMoney(iofN, 'BRL')}</PreviewLine>
            </>
          )}
          <PreviewLine label="Fatura">{card.name} · vence dia {card.due_day}</PreviewLine>
          {catId && <PreviewLine label="Categoria"><CategoryDot categories={categories} id={catId} /></PreviewLine>}
        </Preview>
      )}

      <NotesAttachmentsField
        notes={notes} onNotesChange={setNotes}
        files={drafts} onFilesChange={setDrafts}
        persisted={persistedAttachments} onRemovePersisted={onRemovePersistedAttachment}
        placeholder="ex: motivo, contexto…"
      />
      {error && <p className="text-[12px] text-red-600 dark:text-red-400">{error}</p>}
      {warning && <p className="text-[12px] text-amber-600 dark:text-amber-400">{warning}</p>}
    </ComposerShell>
  )
}

/* ── Transferência entre contas próprias ─────────────────────────────── */

export function TransferComposer({
  accounts, categories, onCreate, onClose,
}: {
  accounts: AccountOut[]
  categories: CategoryOut[]
  onCreate: (data: TransferPayload) => Promise<TransactionOut[]>
  onClose: () => void
}) {
  const checkings = accounts.filter(a => a.account_type === 'checking' && a.is_active)
  const [fromState, setFromId] = useState('')
  const [toState, setToId] = useState('')
  const fromId = fromState || checkings[0]?.id || ''
  const toId = toState || checkings.find(c => c.id !== fromId)?.id || ''
  const [date, setDate] = useState(today())
  const [out, setOut] = useState('')
  const [inn, setInn] = useState('')
  const [desc, setDesc] = useState('Transferência entre contas')
  const [catId, setCatId] = useState('')
  const [notes, setNotes] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const from = accounts.find(a => a.id === fromId)
  const to = accounts.find(a => a.id === toId)
  const cross = !!from && !!to && from.currency !== to.currency
  const outN = num(out)
  const inN = num(inn)
  const implied = cross && outN > 0 && inN > 0
    ? (from!.currency === 'BRL' ? outN / inN : inN / outN)
    : null
  const valid = !!from && !!to && fromId !== toId && outN > 0 && (!cross || inN > 0)

  async function submit() {
    setError('')
    setSaving(true)
    try {
      await onCreate({
        from_account_id: fromId, to_account_id: toId, event_date: date,
        amount_out: outN, amount_in: cross ? inN : null,
        description: desc.trim() || undefined, category_id: catId || null,
        notes: notes.trim() || null,
      })
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Erro ao salvar.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <ComposerShell
      formId="transfer-form" title="Transferência" subtitle="Entre contas correntes próprias · não é despesa"
      onClose={onClose} onSubmit={submit} valid={valid} saving={saving} saveLabel="Salvar"
    >
      <div className="grid grid-cols-2 gap-4">
        <Field label="De">
          <select value={fromId} onChange={e => setFromId(e.target.value)} className={inputCls} aria-label="De">
            {checkings.map(c => <option key={c.id} value={c.id}>{c.name} · {c.currency}</option>)}
          </select>
        </Field>
        <Field label="Para">
          <select value={toId} onChange={e => setToId(e.target.value)} className={inputCls} aria-label="Para">
            {checkings.map(c => <option key={c.id} value={c.id}>{c.name} · {c.currency}</option>)}
          </select>
        </Field>
        <Field label="Data">
          <input type="date" value={date} onChange={e => setDate(e.target.value)} required className={inputCls} aria-label="Data" />
        </Field>
        <Field label={`Valor que saiu · ${from?.currency ?? 'BRL'}`}>
          <input value={out} onChange={e => setOut(e.target.value)} aria-label="Valor que saiu"
            placeholder="ex: 5.279,79" className={`${inputCls} tnum`} />
        </Field>
        {cross && (
          <Field label={`Valor que entrou · ${to!.currency}`} hint="moedas diferentes">
            <input value={inn} onChange={e => setInn(e.target.value)} aria-label="Valor que entrou"
              placeholder="ex: 1.000,00" className={`${inputCls} tnum`} />
          </Field>
        )}
        <Field label="Categoria" hint="opcional">
          <CategorySelect categories={categories} value={catId} onChange={setCatId} filterKind="TRANSFER" />
        </Field>
        <Field label="Descrição" span2>
          <input value={desc} onChange={e => setDesc(e.target.value)} aria-label="Descrição" className={inputCls} />
        </Field>
      </div>

      {fromId === toId && <p className="text-[12px] text-amber-600 dark:text-amber-400">Origem e destino são a mesma conta.</p>}

      {outN > 0 && from && to && fromId !== toId && (
        <Preview>
          <PreviewLine label={from.name}><span className="tnum text-red-500 dark:text-red-400">{fmtMoney(-outN, from.currency, { sign: true })}</span></PreviewLine>
          <PreviewLine label={to.name}>
            <span className="tnum text-emerald-500 dark:text-emerald-400">{fmtMoney(cross ? inN : outN, to.currency, { sign: true })}</span>
          </PreviewLine>
          {implied != null && <PreviewLine label="Cotação implícita">R$ {implied.toFixed(4)} / US$</PreviewLine>}
        </Preview>
      )}

      <Field label="Notas" hint="opcional">
        <textarea value={notes} onChange={e => setNotes(e.target.value)} rows={2} aria-label="Notas"
          placeholder="ex: remessa, motivo…" className={`${inputCls} h-auto py-2`} />
      </Field>
      {error && <p className="text-[12px] text-red-600 dark:text-red-400">{error}</p>}
    </ComposerShell>
  )
}
