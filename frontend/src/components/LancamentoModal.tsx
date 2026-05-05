import { useEffect, useState } from 'react'
import {
  type AssetClass,
  type AssetOut,
  type LancamentoOut,
  type LancamentoRequest,
  type LancamentoType,
  LANCAMENTO_TYPE_LABELS,
} from '../lib/api'

const ALL_TYPES: LancamentoType[] = [
  'COMPRA',
  'VENDA',
  'DIVIDENDO',
  'JUROS',
  'JCP',
  'COME_COTAS',
  'BONIFICACAO',
  'SUBSCRICAO',
  'RESGATE_TOTAL',
]

// Asset classes that are NOT cotado — show a single "Valor" input instead of qty/price.
const NON_COTADO_CLASSES: AssetClass[] = ['FIXED_INCOME', 'FGTS', 'PRIVATE_PENSION', 'CASH']

const QUANTITY_REQUIRED: LancamentoType[] = ['COMPRA', 'VENDA', 'BONIFICACAO', 'SUBSCRICAO', 'RESGATE_TOTAL']
const UNIT_PRICE_REQUIRED: LancamentoType[] = ['COMPRA', 'VENDA', 'SUBSCRICAO', 'RESGATE_TOTAL']
const UNIT_PRICE_HIDDEN: LancamentoType[] = ['DIVIDENDO', 'JUROS', 'JCP', 'COME_COTAS', 'BONIFICACAO']
const QUANTITY_HIDDEN: LancamentoType[] = ['DIVIDENDO', 'JUROS', 'JCP', 'COME_COTAS']
const GROSS_REQUIRED: LancamentoType[] = ['DIVIDENDO', 'JUROS', 'JCP', 'COME_COTAS']
const TAX_REQUIRED: LancamentoType[] = ['COME_COTAS']
const FEE_TAX_HIDDEN: LancamentoType[] = ['BONIFICACAO']
// Types that show the brokerage-note number input.
const NOTA_NEGOCIACAO_TYPES: LancamentoType[] = ['COMPRA', 'VENDA', 'RESGATE_TOTAL', 'SUBSCRICAO']

interface Props {
  initial?: LancamentoOut
  /** Pre-selected asset (used when opening from /assets detail). */
  preselectedAsset?: AssetOut
  assets: AssetOut[]
  onSave: (data: LancamentoRequest) => Promise<void>
  onClose: () => void
}

export default function LancamentoModal({ initial, preselectedAsset, assets, onSave, onClose }: Props) {
  const [type, setType] = useState<LancamentoType>(initial?.type ?? 'COMPRA')
  const [assetId, setAssetId] = useState<string>(
    initial?.asset_id ?? preselectedAsset?.id ?? assets[0]?.id ?? ''
  )
  const [eventDate, setEventDate] = useState(initial?.event_date ?? new Date().toISOString().slice(0, 10))
  const [settlementDate, setSettlementDate] = useState(initial?.settlement_date ?? '')
  const [quantity, setQuantity] = useState(initial?.quantity != null ? String(initial.quantity) : '')
  const [unitPrice, setUnitPrice] = useState(initial?.unit_price != null ? String(initial.unit_price) : '')
  const [grossAmount, setGrossAmount] = useState(initial?.gross_amount != null ? String(initial.gross_amount) : '')
  const [fee, setFee] = useState(initial?.fee != null ? String(initial.fee) : '')
  const [tax, setTax] = useState(initial?.tax != null ? String(initial.tax) : '')
  const [currency, setCurrency] = useState<'BRL' | 'USD'>(initial?.currency ?? preselectedAsset?.currency ?? 'BRL')
  const [fxRate, setFxRate] = useState(initial?.fx_rate != null ? String(initial.fx_rate) : '1.0')
  const [notes, setNotes] = useState(initial?.notes ?? '')
  const [notaNegociacao, setNotaNegociacao] = useState(initial?.nota_negociacao_number ?? '')

  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [confirmInactive, setConfirmInactive] = useState(false)

  const selectedAsset = assets.find(a => a.id === assetId) ?? preselectedAsset
  const assetInactive = !!selectedAsset && selectedAsset.is_active === false

  // When the asset changes, default currency to the asset's currency
  // and reset the inactive-confirmation checkbox.
  useEffect(() => {
    if (selectedAsset) setCurrency(selectedAsset.currency)
    setConfirmInactive(false)
  }, [assetId])  // eslint-disable-line react-hooks/exhaustive-deps

  const isNonCotado = !!selectedAsset && NON_COTADO_CLASSES.includes(selectedAsset.asset_class)
  const isCotadoOrValueType = ['COMPRA', 'VENDA', 'SUBSCRICAO', 'RESGATE_TOTAL'].includes(type)
  // For non-cotado assets on COMPRA/VENDA/SUBSCRICAO/RESGATE_TOTAL, hide qty/unit_price
  // entirely and show a single "Valor" (gross_amount) input instead.
  const useValueOnly = isNonCotado && isCotadoOrValueType
  const showQuantity = !QUANTITY_HIDDEN.includes(type) && !useValueOnly
  const showUnitPrice = !UNIT_PRICE_HIDDEN.includes(type) && !useValueOnly
  const showFeeTax = !FEE_TAX_HIDDEN.includes(type)
  const grossRequired = GROSS_REQUIRED.includes(type) || useValueOnly
  const showNotaNegociacao = NOTA_NEGOCIACAO_TYPES.includes(type)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    setSaving(true)
    try {
      const payload: LancamentoRequest = {
        asset_id: assetId,
        type,
        event_date: eventDate,
        settlement_date: settlementDate || null,
        currency,
        fx_rate: fxRate ? parseFloat(fxRate) : 1.0,
        notes: notes.trim() || null,
      }
      if (showQuantity && quantity) payload.quantity = parseFloat(quantity)
      if (showUnitPrice && unitPrice) payload.unit_price = parseFloat(unitPrice)
      if (grossAmount) payload.gross_amount = parseFloat(grossAmount)
      if (showFeeTax && fee) payload.fee = parseFloat(fee)
      if (showFeeTax && tax) payload.tax = parseFloat(tax)
      if (showNotaNegociacao && notaNegociacao.trim()) {
        payload.nota_negociacao_number = notaNegociacao.trim()
      }
      // For non-cotado COMPRA/VENDA/etc., explicitly null out qty/unit_price.
      if (useValueOnly) {
        payload.quantity = null
        payload.unit_price = null
      }
      await onSave(payload)
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Erro ao salvar.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="w-full max-w-xl max-h-[90vh] overflow-y-auto bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-700 shadow-xl p-6">
        <h2 className="text-base font-semibold text-gray-900 dark:text-white mb-5">
          {initial ? 'Editar Lançamento' : 'Novo Lançamento'}
        </h2>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-sm text-gray-700 dark:text-gray-300 mb-1">Tipo</label>
              <select
                value={type}
                onChange={e => setType(e.target.value as LancamentoType)}
                disabled={!!initial}
                className="w-full px-3.5 py-2 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 disabled:opacity-60"
              >
                {ALL_TYPES.map(t => (
                  <option key={t} value={t}>{LANCAMENTO_TYPE_LABELS[t]}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-sm text-gray-700 dark:text-gray-300 mb-1">Data do evento</label>
              <input
                type="date"
                value={eventDate}
                onChange={e => setEventDate(e.target.value)}
                required
                max={new Date().toISOString().slice(0, 10)}
                className="w-full px-3.5 py-2 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
              />
            </div>
          </div>

          <div>
            <label className="block text-sm text-gray-700 dark:text-gray-300 mb-1">Ativo</label>
            <select
              value={assetId}
              onChange={e => setAssetId(e.target.value)}
              required
              disabled={!!initial || !!preselectedAsset}
              className="w-full px-3.5 py-2 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 disabled:opacity-60"
            >
              {assets.map(a => (
                <option key={a.id} value={a.id}>
                  {a.ticker ? `${a.ticker} — ` : ''}{a.name} ({a.financial_institution_name}){a.is_active === false ? ' · INATIVO' : ''}
                </option>
              ))}
            </select>
            {assetInactive && (
              <div className="mt-2 p-3 rounded-lg bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 text-sm">
                <p className="text-amber-800 dark:text-amber-200 font-medium mb-1">
                  Atenção: este ativo está desativado.
                </p>
                <p className="text-amber-700 dark:text-amber-300 mb-2">
                  Você está prestes a registrar um lançamento contra um ativo desativado.
                  Isso é incomum no fluxo manual — geralmente acontece em importações de histórico.
                </p>
                <label className="flex items-center gap-2 cursor-pointer select-none">
                  <input
                    type="checkbox"
                    checked={confirmInactive}
                    onChange={e => setConfirmInactive(e.target.checked)}
                    className="w-4 h-4 rounded border-amber-300 text-amber-600 focus:ring-amber-500"
                  />
                  <span className="text-amber-800 dark:text-amber-200">
                    Confirmo que quero registrar mesmo assim.
                  </span>
                </label>
              </div>
            )}
          </div>

          {(showQuantity || showUnitPrice) && (
            <div className="grid grid-cols-2 gap-3">
              {showQuantity && (
                <div>
                  <label className="block text-sm text-gray-700 dark:text-gray-300 mb-1">
                    Quantidade {QUANTITY_REQUIRED.includes(type) && <span className="text-red-500">*</span>}
                  </label>
                  <input
                    type="number"
                    step="0.00000001"
                    value={quantity}
                    onChange={e => setQuantity(e.target.value)}
                    required={QUANTITY_REQUIRED.includes(type)}
                    className="w-full px-3.5 py-2 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  />
                </div>
              )}
              {showUnitPrice && (
                <div>
                  <label className="block text-sm text-gray-700 dark:text-gray-300 mb-1">
                    Preço unitário {UNIT_PRICE_REQUIRED.includes(type) && <span className="text-red-500">*</span>}
                  </label>
                  <input
                    type="number"
                    step="0.00000001"
                    value={unitPrice}
                    onChange={e => setUnitPrice(e.target.value)}
                    required={UNIT_PRICE_REQUIRED.includes(type)}
                    className="w-full px-3.5 py-2 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  />
                </div>
              )}
            </div>
          )}

          <div className="grid grid-cols-3 gap-3">
            <div>
              <label className="block text-sm text-gray-700 dark:text-gray-300 mb-1">
                {useValueOnly ? 'Valor' : 'Bruto'} {grossRequired && <span className="text-red-500">*</span>}
                {!grossRequired && <span className="text-xs text-gray-400"> (calc.)</span>}
              </label>
              <input
                type="number"
                step="0.01"
                value={grossAmount}
                onChange={e => setGrossAmount(e.target.value)}
                required={grossRequired}
                placeholder={grossRequired ? '' : '(opcional)'}
                className="w-full px-3.5 py-2 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
              />
            </div>
            {showFeeTax && (
              <>
                <div>
                  <label className="block text-sm text-gray-700 dark:text-gray-300 mb-1">Taxa</label>
                  <input
                    type="number"
                    step="0.01"
                    value={fee}
                    onChange={e => setFee(e.target.value)}
                    className="w-full px-3.5 py-2 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  />
                </div>
                <div>
                  <label className="block text-sm text-gray-700 dark:text-gray-300 mb-1">
                    Imposto {TAX_REQUIRED.includes(type) && <span className="text-red-500">*</span>}
                  </label>
                  <input
                    type="number"
                    step="0.01"
                    value={tax}
                    onChange={e => setTax(e.target.value)}
                    required={TAX_REQUIRED.includes(type)}
                    className="w-full px-3.5 py-2 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  />
                </div>
              </>
            )}
          </div>

          <div className="grid grid-cols-3 gap-3">
            <div>
              <label className="block text-sm text-gray-700 dark:text-gray-300 mb-1">Moeda</label>
              <select
                value={currency}
                onChange={e => setCurrency(e.target.value as 'BRL' | 'USD')}
                className="w-full px-3.5 py-2 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
              >
                <option value="BRL">BRL</option>
                <option value="USD">USD</option>
              </select>
            </div>
            <div>
              <label className="block text-sm text-gray-700 dark:text-gray-300 mb-1">Câmbio (FX)</label>
              <input
                type="number"
                step="0.00000001"
                value={fxRate}
                onChange={e => setFxRate(e.target.value)}
                placeholder="1.0"
                title="Cotação do dia (PTAX automático futuramente)"
                className="w-full px-3.5 py-2 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
              />
              <p className="text-[11px] text-gray-400 mt-1">Cotação do dia (PTAX automático futuramente)</p>
            </div>
            <div>
              <label className="block text-sm text-gray-700 dark:text-gray-300 mb-1">Liquidação</label>
              <input
                type="date"
                value={settlementDate}
                onChange={e => setSettlementDate(e.target.value)}
                className="w-full px-3.5 py-2 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
              />
            </div>
          </div>

          {showNotaNegociacao && (
            <div>
              <label className="block text-sm text-gray-700 dark:text-gray-300 mb-1">
                Nº Nota de Corretagem <span className="text-xs text-gray-400">(opcional)</span>
              </label>
              <input
                type="text"
                value={notaNegociacao}
                onChange={e => setNotaNegociacao(e.target.value)}
                maxLength={50}
                placeholder="Ex: 12345"
                className="w-full px-3.5 py-2 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 font-mono"
              />
            </div>
          )}

          <div>
            <label className="block text-sm text-gray-700 dark:text-gray-300 mb-1">Notas</label>
            <textarea
              value={notes}
              onChange={e => setNotes(e.target.value)}
              rows={2}
              className="w-full px-3.5 py-2 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
          </div>

          {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}

          <div className="flex justify-end gap-3 pt-2">
            <button type="button" onClick={onClose} className="px-4 py-2 rounded-lg text-sm text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors">
              Cancelar
            </button>
            <button type="submit" disabled={saving || (assetInactive && !confirmInactive)} className="px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-700 disabled:opacity-60 text-white text-sm font-medium transition-colors">
              {saving ? 'Salvando…' : 'Salvar'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
