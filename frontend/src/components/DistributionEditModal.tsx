/* Modal de edição rápida de Distribution row a partir da tabela
 * "Eventos do mês" do snapshot. Espelha o padrão do SnapshotItemEditModal
 * (ESC fecha, Enter salva, Cmd+Enter no textarea de notas). */
import { useEffect, useRef, useState } from 'react'
import { Trash2, X } from 'lucide-react'

import {
  api,
  type DistributionOut,
  type DistributionRequest,
  type DistributionType,
} from '../lib/api'
import { parseDecimal } from '../lib/parseDecimal'

interface Props {
  distribution: DistributionOut
  onSaved: (updated: DistributionOut) => void
  onDeleted: (id: string) => void
  onClose: () => void
}

const TYPE_OPTIONS: { value: DistributionType; label: string }[] = [
  { value: 'DIVIDEND', label: 'Dividendo' },
  { value: 'JCP', label: 'JCP' },
  { value: 'INTEREST', label: 'Juros / Cupom' },
  { value: 'SECURITIES_LENDING', label: 'Aluguel' },
]

function fmtInput(n: number | null): string {
  if (n == null) return ''
  return n.toFixed(2).replace('.', ',')
}

export default function DistributionEditModal({
  distribution, onSaved, onDeleted, onClose,
}: Props) {
  const [type, setType] = useState<DistributionType>(distribution.type as DistributionType)
  const [gross, setGross] = useState(fmtInput(distribution.gross_amount))
  const [tax, setTax] = useState(fmtInput(distribution.tax))
  const [net, setNet] = useState(fmtInput(distribution.net_amount))
  const [notes, setNotes] = useState(distribution.notes ?? '')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    inputRef.current?.focus()
    inputRef.current?.select()
  }, [])

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') { e.preventDefault(); onClose(); return }
      if (e.key !== 'Enter') return
      const t = e.target as HTMLElement | null
      const inTextarea = t?.tagName === 'TEXTAREA'
      if (inTextarea && !(e.metaKey || e.ctrlKey)) return
      e.preventDefault()
      void submit()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [type, gross, tax, net, notes])

  async function submit() {
    if (busy) return
    const grossN = parseDecimal(gross)
    if (grossN == null || grossN < 0) {
      setErr('Bruto inválido.'); return
    }
    const taxN = tax.trim() === '' ? null : parseDecimal(tax)
    const netN = net.trim() === '' ? null : parseDecimal(net)
    if (taxN != null && taxN < 0) { setErr('IRRF inválido.'); return }
    if (netN != null && netN < 0) { setErr('Líquido inválido.'); return }
    setBusy(true); setErr(null)
    try {
      const body: DistributionRequest = {
        financial_institution_id: distribution.financial_institution_id,
        asset_id: distribution.asset_id,
        type,
        event_date: distribution.event_date,
        gross_amount: grossN,
        tax: taxN,
        net_amount: netN ?? grossN - (taxN ?? 0),
        currency: distribution.currency,
        fx_rate: distribution.fx_rate,
        notes: notes.trim() || null,
      }
      const updated = await api.updateDistribution(distribution.id, body)
      onSaved(updated)
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Erro')
      setBusy(false)
    }
  }

  async function handleDelete() {
    if (busy) return
    setBusy(true); setErr(null)
    try {
      await api.deactivateDistribution(distribution.id)
      onDeleted(distribution.id)
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Erro')
      setBusy(false)
      setConfirmDelete(false)
    }
  }

  const ccySymbol = distribution.currency === 'USD' ? 'US$' : 'R$'

  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center bg-black/60 p-4"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
    >
      <div
        className="w-full max-w-md bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-700 shadow-2xl flex flex-col max-h-[90vh]"
        onClick={e => e.stopPropagation()}
      >
        <div className="px-5 py-3 border-b border-gray-200 dark:border-gray-800 flex items-center justify-between">
          <div className="min-w-0">
            <div className="text-sm font-semibold truncate">
              {distribution.asset_ticker ?? distribution.asset_name ?? 'Provento'}
            </div>
            <div className="text-[10px] text-gray-500 truncate">
              {distribution.event_date} · {distribution.financial_institution_name}
            </div>
          </div>
          <button
            onClick={onClose}
            className="w-7 h-7 inline-flex items-center justify-center rounded-md text-gray-400 hover:text-gray-700 dark:hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800"
            aria-label="Fechar"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="p-5 space-y-4 overflow-y-auto">
          <label className="block">
            <span className="text-[11px] uppercase tracking-wider font-medium text-gray-500">Tipo</span>
            <select
              value={type}
              onChange={e => setType(e.target.value as DistributionType)}
              className="mt-1 w-full h-9 px-2 text-[14px] rounded-lg bg-gray-50 dark:bg-gray-800/40 border border-gray-300 dark:border-gray-700 focus:outline-none focus:border-indigo-500"
            >
              {TYPE_OPTIONS.map(o => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
          </label>

          <div className="grid grid-cols-2 gap-3">
            <label className="block">
              <span className="text-[11px] uppercase tracking-wider font-medium text-gray-500">Bruto</span>
              <div className="mt-1 flex items-center gap-2 rounded-lg border border-gray-300 dark:border-gray-700 px-2 focus-within:border-indigo-500">
                <span className="text-[12px] text-gray-500">{ccySymbol}</span>
                <input
                  ref={inputRef}
                  type="text"
                  inputMode="decimal"
                  value={gross}
                  onChange={e => { setGross(e.target.value); setErr(null) }}
                  placeholder="0,00"
                  className="flex-1 h-9 bg-transparent text-[14px] tnum outline-none"
                />
              </div>
            </label>
            <label className="block">
              <span className="text-[11px] uppercase tracking-wider font-medium text-gray-500">IRRF</span>
              <div className="mt-1 flex items-center gap-2 rounded-lg border border-gray-300 dark:border-gray-700 px-2 focus-within:border-indigo-500">
                <span className="text-[12px] text-gray-500">{ccySymbol}</span>
                <input
                  type="text"
                  inputMode="decimal"
                  value={tax}
                  onChange={e => { setTax(e.target.value); setErr(null) }}
                  placeholder="0,00"
                  className="flex-1 h-9 bg-transparent text-[14px] tnum outline-none"
                />
              </div>
            </label>
          </div>

          <label className="block">
            <span className="text-[11px] uppercase tracking-wider font-medium text-gray-500">
              Líquido (deixe em branco pra calcular = bruto − IRRF)
            </span>
            <div className="mt-1 flex items-center gap-2 rounded-lg border border-gray-300 dark:border-gray-700 px-2 focus-within:border-indigo-500">
              <span className="text-[12px] text-gray-500">{ccySymbol}</span>
              <input
                type="text"
                inputMode="decimal"
                value={net}
                onChange={e => { setNet(e.target.value); setErr(null) }}
                placeholder="auto"
                className="flex-1 h-9 bg-transparent text-[14px] tnum outline-none"
              />
            </div>
          </label>

          <label className="block">
            <span className="text-[11px] uppercase tracking-wider font-medium text-gray-500">Notas</span>
            <textarea
              value={notes}
              onChange={e => setNotes(e.target.value)}
              rows={2}
              placeholder="ex: corrigi valor lendo extrato XP"
              className="mt-1 w-full p-2 text-[12px] rounded-lg bg-gray-50 dark:bg-gray-800/40 border border-gray-200 dark:border-gray-800 placeholder:text-gray-500 focus:outline-none focus:border-indigo-500"
            />
          </label>

          {err && (
            <div className="text-[11px] text-red-600 dark:text-red-400">{err}</div>
          )}
        </div>

        <div className="px-5 py-3 border-t border-gray-200 dark:border-gray-800 flex items-center justify-between">
          <div className="flex items-center gap-2">
            {confirmDelete ? (
              <>
                <span className="text-[11px] text-red-600 dark:text-red-400">Apagar provento?</span>
                <button
                  onClick={() => void handleDelete()}
                  disabled={busy}
                  className="h-8 px-3 inline-flex items-center gap-1.5 rounded-lg text-[12px] bg-red-600 hover:bg-red-500 text-white disabled:opacity-50"
                >
                  {busy ? 'Apagando…' : 'Sim, apagar'}
                </button>
                <button
                  onClick={() => setConfirmDelete(false)}
                  disabled={busy}
                  className="h-8 px-2 text-[12px] text-gray-500 hover:text-gray-700 dark:hover:text-gray-300"
                >
                  cancelar
                </button>
              </>
            ) : (
              <button
                onClick={() => setConfirmDelete(true)}
                disabled={busy}
                title="Apagar este provento (fica restaurável em Incluir inativos)"
                className="h-8 w-8 inline-flex items-center justify-center rounded-lg text-gray-500 hover:text-red-500 hover:bg-red-500/10 disabled:opacity-50"
              >
                <Trash2 className="w-4 h-4" />
              </button>
            )}
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={onClose}
              disabled={busy}
              className="h-8 px-3 inline-flex items-center gap-1.5 rounded-lg text-[12px] bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700 disabled:opacity-50"
            >
              Cancelar
            </button>
            <button
              onClick={() => void submit()}
              disabled={busy || confirmDelete}
              className="h-9 px-4 inline-flex items-center gap-1.5 rounded-lg text-[13px] font-medium bg-emerald-500 hover:bg-emerald-400 disabled:opacity-50 disabled:cursor-not-allowed text-white"
            >
              {busy ? 'Salvando…' : 'Salvar'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
