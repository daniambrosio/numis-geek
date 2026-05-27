import { useEffect, useMemo, useRef, useState } from 'react'
import { X } from 'lucide-react'
import {
  api,
  type AssetOut, type OptionCreateRequest, type OptionOut, type OptionType,
  type ParsedOptionTicker,
} from '../lib/api'

// Underlyings allowed for new options. Spec 36 §2.2: `STOCK/REIT/ETF` only —
// no options-on-options, no FGTS, etc.
const UNDERLYING_CLASSES = new Set(['STOCK', 'REIT', 'ETF'])

interface Props {
  /** Pre-selected underlying. When omitted, the modal shows an asset
   *  picker as the first field (Spec 36 §2.2). */
  underlying?: AssetOut
  /** Used to populate the picker when `underlying` is absent. */
  candidates?: AssetOut[]
  onClose: () => void
  onSaved: (asset?: OptionOut) => void
}

export default function OptionModal({ underlying, candidates, onClose, onSaved }: Props) {
  const [selectedUnderlyingId, setSelectedUnderlyingId] = useState<string>(underlying?.id ?? '')
  const [ticker, setTicker] = useState('')
  const [parsed, setParsed] = useState<ParsedOptionTicker | null>(null)
  const [optionType, setOptionType] = useState<OptionType>('PUT')
  const [strike, setStrike] = useState('')
  const [expiration, setExpiration] = useState('')
  const [contractSize, setContractSize] = useState('100')
  const [movementType, setMovementType] = useState<'SELL_OPEN' | 'BUY_TO_OPEN'>('SELL_OPEN')
  const [movementDate, setMovementDate] = useState(new Date().toISOString().slice(0, 10))
  const [quantity, setQuantity] = useState('')
  const [pricePerShare, setPricePerShare] = useState('')
  const [fee, setFee] = useState('0')
  const [notes, setNotes] = useState('')
  const [parsing, setParsing] = useState(false)
  const [saving, setSaving] = useState(false)
  const [savingAndNew, setSavingAndNew] = useState(false)
  const [error, setError] = useState('')
  const [toast, setToast] = useState<string | null>(null)
  const tickerRef = useRef<HTMLInputElement>(null)

  // Filter candidates by class — `underlying` prop bypasses the picker.
  const pickerOptions = useMemo(() => {
    if (underlying || !candidates) return []
    return candidates
      .filter(a => UNDERLYING_CLASSES.has(a.asset_class) && a.is_active !== false)
      .sort((a, b) =>
        (a.ticker ?? a.name).localeCompare(b.ticker ?? b.name, 'pt-BR'),
      )
  }, [underlying, candidates])

  const selectedUnderlying: AssetOut | undefined =
    underlying ?? candidates?.find(a => a.id === selectedUnderlyingId)

  // Parse ticker automatically (uses the selected underlying's price as hint).
  useEffect(() => {
    const t = ticker.trim().toUpperCase()
    if (t.length < 5) {
      setParsed(null)
      return
    }
    setParsing(true)
    api.parseOption(t, selectedUnderlying?.current_price ?? undefined)
      .then(p => {
        setParsed(p)
        setOptionType(p.option_type)
        setStrike(String(p.strike_suggested))
      })
      .catch(() => setParsed(null))
      .finally(() => setParsing(false))
  }, [ticker, selectedUnderlying?.current_price])

  function buildBody(): OptionCreateRequest | null {
    if (!selectedUnderlying) {
      setError('Selecione o underlying.')
      return null
    }
    if (!ticker || !strike || !expiration || !quantity || !pricePerShare) {
      setError('Preencha ticker, strike, vencimento, quantidade e preço.')
      return null
    }
    return {
      ticker: ticker.toUpperCase().trim(),
      underlying_id: selectedUnderlying.id,
      account_id: selectedUnderlying.account_id,
      option_type: optionType,
      strike_price: Number(strike),
      expiration_date: expiration,
      contract_size: Number(contractSize) || 100,
      movement_type: movementType,
      movement_date: movementDate,
      quantity: Number(quantity),
      price_per_share: Number(pricePerShare),
      fee: Number(fee) || 0,
      notes: notes || undefined,
    }
  }

  async function save({ keepOpen }: { keepOpen: boolean }) {
    setError('')
    const body = buildBody()
    if (!body) return
    keepOpen ? setSavingAndNew(true) : setSaving(true)
    try {
      const created = await api.createOption(body)
      const premium = body.quantity * body.price_per_share
      onSaved(created)
      if (keepOpen) {
        // Reset everything EXCEPT underlying + optionType (Spec 36 §2.3 —
        // user typically opens multiple PUTs in a row).
        setTicker('')
        setParsed(null)
        setStrike('')
        setExpiration('')
        setQuantity('')
        setPricePerShare('')
        setFee('0')
        setNotes('')
        setToast(`Opção ${body.ticker} criada · prêmio R$ ${premium.toFixed(2)}`)
        setTimeout(() => setToast(null), 3000)
        // Focus back on ticker for fast batch entry.
        setTimeout(() => tickerRef.current?.focus(), 0)
      } else {
        onClose()
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setSaving(false)
      setSavingAndNew(false)
    }
  }

  // ESC closes the modal (consistent with the other composers).
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  const headerTitle = selectedUnderlying
    ? `Nova opção sobre ${selectedUnderlying.ticker || selectedUnderlying.name}`
    : 'Nova opção'

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/50 p-4">
      <div className="w-full max-w-lg bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-700 shadow-xl flex flex-col max-h-[90vh]">
        <div className="px-5 py-3 border-b border-gray-200 dark:border-gray-800 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-gray-900 dark:text-white">{headerTitle}</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="p-5 space-y-3 text-[12px] overflow-y-auto">
          {/* Underlying picker — only when not pre-selected. */}
          {!underlying && (
            <Field label="Underlying (STOCK / REIT / ETF)">
              <select
                value={selectedUnderlyingId}
                onChange={e => setSelectedUnderlyingId(e.target.value)}
                className="w-full h-8 px-2 rounded-md bg-gray-100 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 text-gray-900 dark:text-white"
                data-testid="option-underlying-picker"
              >
                <option value="">Selecione…</option>
                {pickerOptions.map(a => (
                  <option key={a.id} value={a.id}>
                    {(a.ticker || a.name)}{a.current_price != null ? ` · ${a.currency} ${a.current_price.toFixed(2)}` : ''}
                  </option>
                ))}
              </select>
            </Field>
          )}

          <Field label="Ticker B3 (ex: ITUBR364)">
            <input
              ref={tickerRef}
              value={ticker}
              onChange={e => setTicker(e.target.value.toUpperCase())}
              placeholder="ITUBR364"
              className="w-full h-8 px-2 rounded-md bg-gray-100 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 focus:outline-none focus:border-indigo-500 font-mono text-gray-900 dark:text-white"
            />
            {parsing && <div className="text-[10px] text-gray-400">Parseando...</div>}
            {parsed && (
              <div className="text-[10px] text-emerald-600 dark:text-emerald-400">
                Parser: {parsed.option_type} · mês {parsed.month} · strike sugerido R$ {parsed.strike_suggested}
              </div>
            )}
          </Field>

          <div className="grid grid-cols-2 gap-3">
            <Field label="Tipo">
              <select
                value={optionType}
                onChange={e => setOptionType(e.target.value as OptionType)}
                className="w-full h-8 px-2 rounded-md bg-gray-100 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 text-gray-900 dark:text-white"
              >
                <option value="PUT">PUT</option>
                <option value="CALL">CALL</option>
              </select>
            </Field>
            <Field label="Strike (R$)">
              <input
                type="number" step="0.01" value={strike}
                onChange={e => setStrike(e.target.value)}
                className="w-full h-8 px-2 rounded-md bg-gray-100 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 tnum text-gray-900 dark:text-white"
              />
            </Field>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <Field label="Vencimento">
              <input
                type="date" value={expiration}
                onChange={e => setExpiration(e.target.value)}
                className="w-full h-8 px-2 rounded-md bg-gray-100 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 text-gray-900 dark:text-white"
              />
            </Field>
            <Field label="Contract size">
              <input
                type="number" value={contractSize}
                onChange={e => setContractSize(e.target.value)}
                className="w-full h-8 px-2 rounded-md bg-gray-100 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 tnum text-gray-900 dark:text-white"
              />
            </Field>
          </div>

          <div className="border-t border-gray-200 dark:border-gray-800 pt-3 space-y-3">
            <div className="text-[10px] uppercase tracking-wider text-gray-500 dark:text-gray-400 font-semibold">
              Primeira operação
            </div>

            <div className="grid grid-cols-2 gap-3">
              <Field label="Tipo operação">
                <select
                  value={movementType}
                  onChange={e => setMovementType(e.target.value as 'SELL_OPEN' | 'BUY_TO_OPEN')}
                  className="w-full h-8 px-2 rounded-md bg-gray-100 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 text-gray-900 dark:text-white"
                >
                  <option value="SELL_OPEN">Vender pra abrir (lançar)</option>
                  <option value="BUY_TO_OPEN">Comprar pra abrir</option>
                </select>
              </Field>
              <Field label="Data">
                <input
                  type="date" value={movementDate}
                  onChange={e => setMovementDate(e.target.value)}
                  className="w-full h-8 px-2 rounded-md bg-gray-100 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 text-gray-900 dark:text-white"
                />
              </Field>
            </div>

            <div className="grid grid-cols-3 gap-3">
              <Field label="Quantidade">
                <input
                  type="number" value={quantity}
                  onChange={e => setQuantity(e.target.value)}
                  placeholder="1000"
                  className="w-full h-8 px-2 rounded-md bg-gray-100 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 tnum text-gray-900 dark:text-white"
                />
              </Field>
              <Field label="Preço/ação (R$)">
                <input
                  type="number" step="0.01" value={pricePerShare}
                  onChange={e => setPricePerShare(e.target.value)}
                  placeholder="0.09"
                  className="w-full h-8 px-2 rounded-md bg-gray-100 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 tnum text-gray-900 dark:text-white"
                />
              </Field>
              <Field label="Taxa (R$)">
                <input
                  type="number" step="0.01" value={fee}
                  onChange={e => setFee(e.target.value)}
                  className="w-full h-8 px-2 rounded-md bg-gray-100 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 tnum text-gray-900 dark:text-white"
                />
              </Field>
            </div>
          </div>

          <Field label="Notas">
            <textarea
              value={notes}
              onChange={e => setNotes(e.target.value)}
              rows={2}
              className="w-full px-2 py-1.5 rounded-md bg-gray-100 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 text-gray-900 dark:text-white"
            />
          </Field>

          {error && (
            <div className="text-[11px] text-red-600 dark:text-red-400">{error}</div>
          )}
          {toast && (
            <div className="text-[11px] text-emerald-600 dark:text-emerald-400" data-testid="option-toast">{toast}</div>
          )}
        </div>

        <div className="px-5 py-3 border-t border-gray-200 dark:border-gray-800 flex justify-end gap-2">
          <button
            onClick={onClose}
            disabled={saving || savingAndNew}
            className="h-8 px-3 inline-flex items-center rounded-md text-[12px] text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800"
          >
            Cancelar
          </button>
          <button
            onClick={() => void save({ keepOpen: true })}
            disabled={saving || savingAndNew}
            className="h-8 px-3 inline-flex items-center rounded-md border border-indigo-500 text-indigo-600 dark:text-indigo-300 text-[12px] font-medium hover:bg-indigo-50 dark:hover:bg-indigo-900/20 disabled:opacity-50"
            data-testid="option-save-and-new"
          >
            {savingAndNew ? 'Salvando…' : 'Salvar e abrir outra'}
          </button>
          <button
            onClick={() => void save({ keepOpen: false })}
            disabled={saving || savingAndNew}
            className="h-8 px-3 inline-flex items-center rounded-md bg-indigo-500 hover:bg-indigo-400 text-white text-[12px] font-medium disabled:opacity-50"
          >
            {saving ? 'Salvando...' : 'Criar opção'}
          </button>
        </div>
      </div>
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="block text-[10px] uppercase tracking-wider text-gray-500 dark:text-gray-400 mb-1">{label}</label>
      {children}
    </div>
  )
}
