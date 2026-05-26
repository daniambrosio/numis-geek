import { useEffect, useMemo, useState } from 'react'
import { X, Sparkles } from 'lucide-react'
import {
  type AssetClass,
  type AssetOut,
  type AssetMovementOut,
  type AssetMovementRequest,
  type AssetMovementType,
} from '../lib/api'

// 6 normal types only — option lifecycle types (SELL_OPEN, BUY_TO_OPEN,
// SELL_TO_CLOSE, BUY_TO_CLOSE, EXERCISED, EXPIRED) are handled via the
// dedicated option flow on the underlying's detail page (`OptionModal` +
// `OpenOptionsCard` actions), per `options-rationale.md` §7 and the
// prototype's MovementComposer.
interface TypeCfg {
  label: string
  hint: string
  qty: boolean
  price: boolean
  fee: boolean
  tax: boolean
}

const TYPE_CFG: Record<string, TypeCfg> = {
  BUY:             { label: 'Compra',        hint: 'compra adiciona à posição',     qty: true,  price: true,  fee: true,  tax: false },
  SELL:            { label: 'Venda',         hint: 'venda reduz a posição',         qty: true,  price: true,  fee: true,  tax: false },
  BONUS:           { label: 'Bonificação',   hint: 'ações grátis · sem custo',      qty: true,  price: false, fee: false, tax: false },
  SUBSCRIPTION:    { label: 'Subscrição',    hint: 'exercício de subscrição',       qty: true,  price: true,  fee: true,  tax: false },
  COME_COTAS:      { label: 'Come-cotas',    hint: 'imposto semestral · BR',        qty: false, price: false, fee: false, tax: true  },
  FULL_REDEMPTION: { label: 'Resgate Total', hint: 'vencimento ou liquidação',      qty: true,  price: true,  fee: false, tax: false },
}

const TYPE_ORDER: AssetMovementType[] = ['BUY', 'SELL', 'BONUS', 'SUBSCRIPTION', 'COME_COTAS', 'FULL_REDEMPTION']

// Non-cotado classes — for BUY/SELL/SUBSCRIPTION/FULL_REDEMPTION, show a
// single "Valor" (gross_amount) input instead of qty × unit_price.
// FIXED_INCOME is intentionally NOT here: Tesouro Direto and debêntures
// have qty + valor_título separately on the broker statement, and even
// CDBs work with qty=1, unit_price=valor. Forcing value-only lost data.
const NON_COTADO_CLASSES: AssetClass[] = ['FGTS', 'PRIVATE_PENSION', 'CASH']
const NOTA_NEGOCIACAO_TYPES: AssetMovementType[] = ['BUY', 'SELL', 'FULL_REDEMPTION', 'SUBSCRIPTION']

interface Props {
  initial?: AssetMovementOut
  /** Pre-selected asset (used when opening from /assets detail). */
  preselectedAsset?: AssetOut
  assets: AssetOut[]
  onSave: (data: AssetMovementRequest) => Promise<void>
  onClose: () => void
}

const num = (s: string): number => {
  const n = parseFloat(s.replace(',', '.'))
  return Number.isFinite(n) ? n : 0
}

const fmtMoney = (n: number, ccy: 'BRL' | 'USD', opts: { sign?: boolean } = {}) => {
  const sign = opts.sign && n > 0 ? '+ ' : opts.sign && n < 0 ? '− ' : ''
  return sign + Math.abs(n).toLocaleString('pt-BR', { style: 'currency', currency: ccy })
}

const fmtNum = (n: number, digits = 2) =>
  n.toLocaleString('pt-BR', { maximumFractionDigits: digits })

export default function MovementComposer({ initial, preselectedAsset, assets, onSave, onClose }: Props) {
  // Asset selector lists ALL assets (incl. OPTION) — same as the prototype's
  // MovementComposer (`index.html:4312-4316`). Option lifecycle types
  // (SELL_OPEN/BUY_TO_OPEN/EXERCISED/EXPIRED) are NOT exposed here; the
  // composer uses the 6 normal types and the backend interprets them
  // according to the asset class.
  const [type, setType] = useState<AssetMovementType>(initial?.type ?? 'BUY')
  const [assetId, setAssetId] = useState<string>(
    initial?.asset_id ?? preselectedAsset?.id ?? assets[0]?.id ?? '',
  )
  const [eventDate, setEventDate] = useState(initial?.event_date ?? new Date().toISOString().slice(0, 10))
  const [quantity, setQuantity] = useState(initial?.quantity != null ? String(initial.quantity) : '')
  const [unitPrice, setUnitPrice] = useState(initial?.unit_price != null ? String(initial.unit_price) : '')
  const [grossAmount, setGrossAmount] = useState(initial?.gross_amount != null ? String(initial.gross_amount) : '')
  const [fee, setFee] = useState(initial?.fee != null ? String(initial.fee) : '')
  const [tax, setTax] = useState(initial?.tax != null ? String(initial.tax) : '')
  const [notes, setNotes] = useState(initial?.notes ?? '')
  const [notaNegociacao, setNotaNegociacao] = useState(initial?.nota_negociacao_number ?? '')
  const [confirmInactive, setConfirmInactive] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const selectedAsset = assets.find(a => a.id === assetId) ?? preselectedAsset

  // Sort by ticker (fallback to name) so native-select type-ahead lands
  // on the ticker the user types — e.g. typing "W" jumps to WEGE3, not
  // to assets whose company name starts with W.
  const sortedAssets = useMemo(() => {
    const key = (a: AssetOut) => (a.ticker || a.name).toLocaleLowerCase('pt-BR')
    return [...assets].sort((a, b) => key(a).localeCompare(key(b), 'pt-BR'))
  }, [assets])
  const cfg = TYPE_CFG[type]
  const ccy: 'BRL' | 'USD' = selectedAsset?.currency ?? 'BRL'
  const isNonCotado = !!selectedAsset && NON_COTADO_CLASSES.includes(selectedAsset.asset_class)
  const isCotadoOrValueType = ['BUY', 'SELL', 'SUBSCRIPTION', 'FULL_REDEMPTION'].includes(type)
  const useValueOnly = isNonCotado && isCotadoOrValueType
  const showQuantity = cfg.qty && !useValueOnly
  const showUnitPrice = cfg.price && !useValueOnly
  // Fee applies to non-cotado too (Tesouro Direto charges custody fee,
  // broker fee, IR retido na fonte — user wants to track these apart
  // from the gross value).
  const showFee = cfg.fee
  const showTax = cfg.tax
  const showNotaNegociacao = NOTA_NEGOCIACAO_TYPES.includes(type)
  const assetInactive = !!selectedAsset && selectedAsset.is_active === false

  // Reset asset-related state when asset changes.
  useEffect(() => { setConfirmInactive(false) }, [assetId])

  // Live preview: Net + position transition.
  const qN = num(quantity), pN = num(unitPrice), feeN = num(fee), tN = num(tax), gN = num(grossAmount)
  let net = 0
  if (useValueOnly) {
    // Non-cotado: gross + optional fee. Fee adds to cost on buy/sub,
    // subtracts from proceeds on sell/redemption (matches backend
    // net_amount calc in asset_movements.py).
    net = type === 'BUY' || type === 'SUBSCRIPTION' ? -(gN + feeN) : (gN - feeN)
  } else if (type === 'BUY')             net = -(qN * pN + feeN)
  else if (type === 'SELL')              net = qN * pN - feeN
  else if (type === 'BONUS')             net = 0
  else if (type === 'SUBSCRIPTION')      net = -(qN * pN + feeN)
  else if (type === 'COME_COTAS')        net = -tN
  else if (type === 'FULL_REDEMPTION')   net = qN * pN

  // Position delta (illustrative — server is source of truth).
  const positionDelta = (type === 'BUY' || type === 'BONUS' || type === 'SUBSCRIPTION') ? qN
                      : (type === 'SELL' || type === 'FULL_REDEMPTION') ? -qN
                      : 0

  // ESC closes
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
      if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
        const form = document.getElementById('movement-form') as HTMLFormElement | null
        form?.requestSubmit()
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  const isValid = !!selectedAsset
    && (cfg.qty && !useValueOnly ? qN > 0 : true)
    && (cfg.price && !useValueOnly ? pN > 0 : true)
    && (cfg.tax ? tN > 0 : true)
    && (useValueOnly ? gN > 0 : true)
    && (!assetInactive || confirmInactive)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!isValid) return
    setError('')
    setSaving(true)
    try {
      const payload: AssetMovementRequest = {
        asset_id: assetId,
        type,
        event_date: eventDate,
        settlement_date: null,
        currency: ccy,
        fx_rate: ccy === 'USD' ? 1.0 : 1.0, // TODO: PTAX integration
        notes: notes.trim() || null,
      }
      if (showQuantity && quantity) payload.quantity = num(quantity)
      if (showUnitPrice && unitPrice) payload.unit_price = num(unitPrice)
      if (useValueOnly || grossAmount) payload.gross_amount = num(grossAmount)
      if (showFee && fee) payload.fee = num(fee)
      if (showTax && tax) payload.tax = num(tax)
      if (showNotaNegociacao && notaNegociacao.trim()) payload.nota_negociacao_number = notaNegociacao.trim()
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
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
      <div className="w-full max-w-2xl max-h-[90vh] bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-800 shadow-2xl flex flex-col">
        {/* Header */}
        <div className="px-6 py-4 border-b border-gray-100 dark:border-gray-800 flex items-start justify-between">
          <div>
            <h2 className="text-base font-semibold text-gray-900 dark:text-white">
              {initial ? 'Editar Lançamento' : 'Novo Lançamento'}
            </h2>
            <p className="text-[12px] text-gray-500 dark:text-gray-400 mt-0.5">
              Movimento de posição em ativo
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="w-7 h-7 inline-flex items-center justify-center rounded-md text-gray-400 hover:text-gray-700 dark:hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Body */}
        <form id="movement-form" onSubmit={handleSubmit} className="px-6 py-5 overflow-y-auto flex-1 scrollbar-thin space-y-5">
          {/* Type picker — 3x2 grid */}
          <div>
            <FieldLabel>Tipo</FieldLabel>
            <div className="grid grid-cols-3 gap-2 mt-1.5">
              {TYPE_ORDER.map(id => {
                const c = TYPE_CFG[id]
                const active = type === id
                return (
                  <button
                    key={id}
                    type="button"
                    onClick={() => setType(id)}
                    disabled={!!initial}
                    className={`px-3 py-2.5 rounded-lg text-left border transition-colors disabled:opacity-60 disabled:cursor-not-allowed ${
                      active
                        ? 'bg-indigo-500/10 border-indigo-500'
                        : 'bg-gray-50 dark:bg-gray-800/30 border-gray-200 dark:border-gray-800 hover:border-gray-400 dark:hover:border-gray-700'
                    }`}
                  >
                    <div className={`text-[12px] font-semibold ${active ? 'text-indigo-700 dark:text-indigo-300' : 'text-gray-700 dark:text-gray-300'}`}>
                      {c.label}
                    </div>
                    <div className="text-[10px] text-gray-500 mt-0.5">{c.hint}</div>
                  </button>
                )
              })}
            </div>
          </div>

          {/* Date + Asset */}
          <div className="grid grid-cols-2 gap-4">
            <Field label="Data do evento">
              <input
                type="date"
                value={eventDate}
                onChange={e => setEventDate(e.target.value)}
                required
                max={new Date().toISOString().slice(0, 10)}
                className={inputCls}
              />
            </Field>
            <Field label="Ativo">
              <select
                value={assetId}
                onChange={e => setAssetId(e.target.value)}
                disabled={!!initial || !!preselectedAsset}
                required
                className={inputCls}
              >
                {sortedAssets.length === 0 && <option value="">Nenhum ativo</option>}
                {sortedAssets.map(a => (
                  <option key={a.id} value={a.id}>
                    {a.ticker ? `${a.ticker} · ` : ''}{a.name}{a.is_active === false ? ' · INATIVO' : ''}
                  </option>
                ))}
              </select>
            </Field>
          </div>

          {/* Numeric fields (conditional per type) */}
          <div className="grid grid-cols-2 gap-4">
            {useValueOnly ? (
              <Field label={`Valor · ${ccy}`}>
                <input
                  type="number" step="0.01" value={grossAmount}
                  onChange={e => setGrossAmount(e.target.value)} required
                  placeholder="ex: 50.000,00"
                  className={inputCls}
                />
              </Field>
            ) : (
              <>
                {showQuantity && (
                  <Field label="Quantidade">
                    <input
                      type="number" step="0.00000001" value={quantity}
                      onChange={e => setQuantity(e.target.value)} required={cfg.qty}
                      placeholder="ex: 100"
                      className={inputCls}
                    />
                  </Field>
                )}
                {showUnitPrice && (
                  <Field label={`Preço unitário · ${ccy}`}>
                    <input
                      type="number" step="0.00000001" value={unitPrice}
                      onChange={e => setUnitPrice(e.target.value)} required={cfg.price}
                      placeholder="ex: 38,90"
                      className={inputCls}
                    />
                  </Field>
                )}
              </>
            )}
            {showFee && (
              <Field label={`Taxa · ${ccy}`} hint="opcional">
                <input
                  type="number" step="0.01" value={fee}
                  onChange={e => setFee(e.target.value)}
                  placeholder="ex: 12,40"
                  className={inputCls}
                />
              </Field>
            )}
            {showTax && (
              <Field label={`Imposto retido · ${ccy}`}>
                <input
                  type="number" step="0.01" value={tax}
                  onChange={e => setTax(e.target.value)} required
                  placeholder="ex: 384,00"
                  className={inputCls}
                />
              </Field>
            )}
          </div>

          {/* Inactive warning */}
          {assetInactive && (
            <div className="p-3 rounded-lg bg-amber-500/10 border border-amber-500/30 text-[12px] text-amber-800 dark:text-amber-300">
              Esse ativo está marcado como zerado.
              <label className="flex items-center gap-2 mt-1.5 cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={confirmInactive}
                  onChange={e => setConfirmInactive(e.target.checked)}
                  className="w-3.5 h-3.5 rounded border-amber-400 text-amber-600 focus:ring-amber-500"
                />
                <span>Confirmo que quero registrar mesmo assim.</span>
              </label>
            </div>
          )}

          {/* Brokerage note number */}
          {showNotaNegociacao && (
            <Field label="Nº Nota de Corretagem" hint="opcional">
              <input
                type="text" value={notaNegociacao}
                onChange={e => setNotaNegociacao(e.target.value)}
                maxLength={50} placeholder="ex: 12345"
                className={`${inputCls} font-mono`}
              />
            </Field>
          )}

          {/* Live preview */}
          {selectedAsset && (
            <div className="rounded-lg bg-indigo-500/5 border border-indigo-500/20 p-3.5 space-y-2">
              <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider font-semibold text-indigo-500 dark:text-indigo-400">
                <Sparkles className="w-3 h-3" />
                Pré-visualização
              </div>
              {showQuantity && showUnitPrice && qN > 0 && pN > 0 && (
                <div className="flex items-center justify-between text-[12px]">
                  <span className="text-gray-500 dark:text-gray-400">Bruto</span>
                  <span className="tnum text-gray-700 dark:text-gray-300">
                    {fmtMoney(qN * pN, ccy)}
                    {feeN > 0 && (
                      <span className="text-gray-400 dark:text-gray-500"> · taxa {fmtMoney(feeN, ccy)}</span>
                    )}
                  </span>
                </div>
              )}
              <div className="flex items-center justify-between">
                <span className="text-[12px] text-gray-500 dark:text-gray-400">Net</span>
                <span className={`tnum text-base font-semibold ${net < 0 ? 'text-red-500 dark:text-red-400' : net > 0 ? 'text-emerald-500 dark:text-emerald-400' : 'text-gray-500'}`}>
                  {fmtMoney(net, ccy, { sign: true })}
                </span>
              </div>
              {cfg.qty && (
                <div className="flex items-center justify-between text-[12px]">
                  <span className="text-gray-500 dark:text-gray-400">Posição</span>
                  <span className="tnum text-gray-700 dark:text-gray-300">
                    {positionDelta !== 0 ? (
                      <>
                        Δ <span className={positionDelta > 0 ? 'text-emerald-500 dark:text-emerald-400 font-semibold' : 'text-red-500 dark:text-red-400 font-semibold'}>
                          {positionDelta > 0 ? '+' : ''}{fmtNum(positionDelta, 4)}
                        </span> {selectedAsset.ticker || selectedAsset.name}
                      </>
                    ) : '—'}
                  </span>
                </div>
              )}
            </div>
          )}

          {/* Notes */}
          <Field label="Notas" hint="opcional · ⌘V cola imagem">
            <textarea
              value={notes}
              onChange={e => setNotes(e.target.value)}
              rows={2}
              placeholder="ex: tese, motivo da compra, link pra notícia…"
              className={`${inputCls} py-2 resize-none`}
            />
          </Field>

          {error && <p className="text-[12px] text-red-600 dark:text-red-400">{error}</p>}
        </form>

        {/* Footer */}
        <div className="px-6 py-3 border-t border-gray-100 dark:border-gray-800 flex items-center justify-between">
          <span className="text-[11px] text-gray-500 dark:text-gray-500">
            <kbd className="px-1.5 py-0.5 mx-0.5 rounded bg-gray-100 dark:bg-gray-800 text-[10px] font-mono">⌘↵</kbd> salvar
            {' · '}
            <kbd className="px-1.5 py-0.5 mx-0.5 rounded bg-gray-100 dark:bg-gray-800 text-[10px] font-mono">esc</kbd> fechar
          </span>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={onClose}
              className="h-8 px-3 inline-flex items-center rounded-md text-[12px] text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
            >
              Cancelar
            </button>
            <button
              type="submit"
              form="movement-form"
              disabled={!isValid || saving}
              className="h-8 px-3 inline-flex items-center gap-1.5 rounded-md bg-indigo-500 hover:bg-indigo-400 text-white text-[12px] font-medium disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {saving ? 'Salvando…' : '✓ Salvar'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

/* ── Primitives ──────────────────────────────────────────────────────── */

function FieldLabel({ children }: { children: React.ReactNode }) {
  return (
    <label className="block text-[10px] uppercase tracking-wider font-semibold text-gray-500 dark:text-gray-400">
      {children}
    </label>
  )
}

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="flex items-baseline justify-between mb-1.5">
        <FieldLabel>{label}</FieldLabel>
        {hint && <span className="text-[10px] text-gray-400 dark:text-gray-600">· {hint}</span>}
      </div>
      {children}
    </div>
  )
}

const inputCls =
  'w-full h-9 px-3 text-[13px] rounded-md bg-gray-50 dark:bg-gray-800/50 border border-gray-200 dark:border-gray-800 text-gray-900 dark:text-white placeholder:text-gray-400 dark:placeholder:text-gray-600 focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500'
