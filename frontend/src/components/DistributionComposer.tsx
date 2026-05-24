import { useEffect, useState } from 'react'
import { Sparkles, X } from 'lucide-react'
import {
  type AssetOut,
  type DistributionOut,
  type DistributionRequest,
  type DistributionType,
  type FinancialInstitutionOut,
} from '../lib/api'

interface TypeCfg {
  label: string
  hint: string
  assetRequired: boolean
}

const TYPE_CFG: Record<DistributionType, TypeCfg> = {
  DIVIDEND:           { label: 'Dividendo',     hint: 'renda variável · isento (PF)',           assetRequired: true  },
  INTEREST:           { label: 'Juros / Cupom', hint: 'renda fixa · cupom',                     assetRequired: true  },
  JCP:                { label: 'JCP',           hint: 'BR · IR retido na fonte',                assetRequired: true  },
  SECURITIES_LENDING: { label: 'Aluguel',       hint: 'empréstimo de ativos · ticker opcional', assetRequired: false },
}

const TYPE_ORDER: DistributionType[] = ['DIVIDEND', 'INTEREST', 'JCP', 'SECURITIES_LENDING']

interface Props {
  initial?: DistributionOut
  institutions: FinancialInstitutionOut[]
  assets: AssetOut[]
  onSave: (data: DistributionRequest) => Promise<void>
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

export default function DistributionComposer({
  initial, institutions, assets, onSave, onClose,
}: Props) {
  const [type, setType] = useState<DistributionType>(initial?.type ?? 'DIVIDEND')
  const [fiId, setFiId] = useState<string>(
    initial?.financial_institution_id ?? institutions[0]?.id ?? '',
  )
  const [assetId, setAssetId] = useState<string>(initial?.asset_id ?? '')
  const [eventDate, setEventDate] = useState(initial?.event_date ?? new Date().toISOString().slice(0, 10))
  const [gross, setGross] = useState(initial?.gross_amount != null ? String(initial.gross_amount) : '')
  const [tax, setTax] = useState(initial?.tax != null ? String(initial.tax) : '')
  const [currency, setCurrency] = useState<'BRL' | 'USD'>(initial?.currency ?? 'BRL')
  const [notes, setNotes] = useState(initial?.notes ?? '')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const cfg = TYPE_CFG[type]
  const selectedAsset = assets.find(a => a.id === assetId)

  // Asset list filtered by selected FI (via asset.account → fi).
  // Since AssetOut already carries financial_institution_id, this is direct.
  const assetsAtSelectedFi = assets.filter(a => a.financial_institution_id === fiId)

  // When FI changes, reset asset selection so the dropdown isn't stale.
  useEffect(() => {
    if (assetId && !assetsAtSelectedFi.some(a => a.id === assetId)) {
      setAssetId('')
    }
  }, [fiId])  // eslint-disable-line react-hooks/exhaustive-deps

  // When an asset is picked, default currency to its currency.
  useEffect(() => {
    if (selectedAsset) setCurrency(selectedAsset.currency)
  }, [assetId])  // eslint-disable-line react-hooks/exhaustive-deps

  // ESC + ⌘↵ shortcuts
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
      if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
        const form = document.getElementById('distribution-form') as HTMLFormElement | null
        form?.requestSubmit()
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  const grossN = num(gross)
  const taxN = num(tax)
  const net = grossN - taxN

  const isValid = !!fiId
    && (cfg.assetRequired ? !!assetId : true)
    && grossN > 0

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!isValid) return
    setError('')
    setSaving(true)
    try {
      const payload: DistributionRequest = {
        financial_institution_id: fiId,
        asset_id: assetId || null,
        type,
        event_date: eventDate,
        gross_amount: grossN,
        tax: taxN > 0 ? taxN : null,
        net_amount: net,
        currency,
        fx_rate: currency === 'USD' ? 1.0 : 1.0,  // TODO: PTAX integration
        notes: notes.trim() || null,
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
              {initial ? 'Editar Provento' : 'Novo Provento'}
            </h2>
            <p className="text-[12px] text-gray-500 dark:text-gray-400 mt-0.5">
              Rendimento, dividendo, JCP ou aluguel
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
        <form id="distribution-form" onSubmit={handleSubmit} className="px-6 py-5 overflow-y-auto flex-1 scrollbar-thin space-y-5">
          {/* Type picker — 2x2 grid */}
          <div>
            <FieldLabel>Tipo</FieldLabel>
            <div className="grid grid-cols-2 gap-2 mt-1.5">
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

          <div className="grid grid-cols-2 gap-4">
            <Field label="Data do evento">
              <input
                type="date" value={eventDate}
                onChange={e => setEventDate(e.target.value)} required
                className={inputCls}
              />
            </Field>
            <Field label="Instituição">
              <select
                value={fiId} onChange={e => setFiId(e.target.value)} required
                className={inputCls}
              >
                {institutions.map(fi => (
                  <option key={fi.id} value={fi.id}>{fi.short_name}</option>
                ))}
              </select>
            </Field>
          </div>

          <Field
            label={`Ativo${cfg.assetRequired ? '' : ' · opcional'}`}
            hint={!cfg.assetRequired ? "ex: Avenue não informa ticker" : undefined}
          >
            <select
              value={assetId} onChange={e => setAssetId(e.target.value)}
              required={cfg.assetRequired}
              className={inputCls}
            >
              <option value="">{cfg.assetRequired ? 'Selecione…' : 'Sem ticker (genérico da IF)'}</option>
              {assetsAtSelectedFi.map(a => (
                <option key={a.id} value={a.id}>
                  {a.ticker ? `${a.ticker} · ${a.name}` : a.name}
                </option>
              ))}
            </select>
          </Field>

          <div className="grid grid-cols-2 gap-4">
            <Field label={`Valor bruto · ${currency}`}>
              <input
                type="number" step="0.01" value={gross}
                onChange={e => setGross(e.target.value)} required
                placeholder="ex: 412,80"
                className={inputCls}
              />
            </Field>
            <Field label={`IR retido · ${currency}`} hint="opcional">
              <input
                type="number" step="0.01" value={tax}
                onChange={e => setTax(e.target.value)}
                placeholder="ex: 51,00"
                className={inputCls}
              />
            </Field>
          </div>

          {/* Live preview */}
          {(grossN > 0 || selectedAsset) && (
            <div className="rounded-lg bg-indigo-500/5 border border-indigo-500/20 p-3.5 space-y-2">
              <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider font-semibold text-indigo-500 dark:text-indigo-400">
                <Sparkles className="w-3 h-3" />
                Pré-visualização
              </div>
              <div className="flex items-center justify-between">
                <span className="text-[12px] text-gray-500 dark:text-gray-400">Líquido</span>
                <span className="tnum text-base font-semibold text-emerald-500 dark:text-emerald-400">
                  {fmtMoney(net, currency, { sign: true })}
                </span>
              </div>
              {selectedAsset && (
                <div className="flex items-center justify-between text-[12px]">
                  <span className="text-gray-500 dark:text-gray-400">Ativo</span>
                  <span className="text-gray-700 dark:text-gray-300 font-mono">
                    {selectedAsset.ticker || selectedAsset.name}
                  </span>
                </div>
              )}
              {!selectedAsset && !cfg.assetRequired && (
                <div className="flex items-center justify-between text-[12px]">
                  <span className="text-gray-500 dark:text-gray-400">Origem</span>
                  <span className="italic text-gray-500">sem ticker · genérico</span>
                </div>
              )}
            </div>
          )}

          <Field label="Notas" hint="opcional · ⌘V cola imagem">
            <textarea
              value={notes} onChange={e => setNotes(e.target.value)}
              rows={2}
              placeholder="ex: trimestre 1T26, link RI…"
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
              form="distribution-form"
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
