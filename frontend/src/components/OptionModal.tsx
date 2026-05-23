import { useEffect, useState } from 'react'
import { X } from 'lucide-react'
import {
  api,
  type AssetOut, type OptionCreateRequest, type OptionType, type ParsedOptionTicker,
} from '../lib/api'

interface Props {
  underlying: AssetOut         // pre-selected underlying asset
  onClose: () => void
  onSaved: () => void
}

export default function OptionModal({ underlying, onClose, onSaved }: Props) {
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
  const [error, setError] = useState('')

  // Parse ticker automatically
  useEffect(() => {
    const t = ticker.trim().toUpperCase()
    if (t.length < 5) {
      setParsed(null)
      return
    }
    setParsing(true)
    api.parseOption(t, underlying.current_price ?? undefined)
      .then(p => {
        setParsed(p)
        setOptionType(p.option_type)
        setStrike(String(p.strike_suggested))
      })
      .catch(() => setParsed(null))
      .finally(() => setParsing(false))
  }, [ticker, underlying.current_price])

  async function handleSave() {
    setError('')
    if (!ticker || !strike || !expiration || !quantity || !pricePerShare) {
      setError('Preencha ticker, strike, vencimento, quantidade e preço.')
      return
    }
    const body: OptionCreateRequest = {
      ticker: ticker.toUpperCase().trim(),
      underlying_id: underlying.id,
      account_id: underlying.account_id,
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
    setSaving(true)
    try {
      await api.createOption(body)
      onSaved()
      onClose()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/50 p-4">
      <div className="w-full max-w-lg bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-700 shadow-xl flex flex-col max-h-[90vh]">
        <div className="px-5 py-3 border-b border-gray-200 dark:border-gray-800 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-gray-900 dark:text-white">
            Nova opção sobre {underlying.ticker || underlying.name}
          </h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="p-5 space-y-3 text-[12px] overflow-y-auto">
          <Field label="Ticker B3 (ex: ITUBR364)">
            <input
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
        </div>

        <div className="px-5 py-3 border-t border-gray-200 dark:border-gray-800 flex justify-end gap-2">
          <button
            onClick={onClose}
            disabled={saving}
            className="h-8 px-3 inline-flex items-center rounded-md text-[12px] text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800"
          >
            Cancelar
          </button>
          <button
            onClick={handleSave}
            disabled={saving}
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
