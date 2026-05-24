/* Spec 28 — manual price edit modal.
 *
 * Disparado pelo botão "Editar preço" do AssetDetail quando
 * asset.price_source === 'MANUAL'. Chama PATCH /assets/{id}/price. */
import { useEffect, useRef, useState } from 'react'

import { api, type AssetOut, type ManualPriceOut } from '../lib/api'
import { formatRelative } from '../lib/price'

interface Props {
  asset: AssetOut
  onClose: () => void
  /** Called with the new server-confirmed price after a successful PATCH. */
  onSaved: (result: ManualPriceOut) => void
}

function fmtCurrent(asset: AssetOut): string {
  if (asset.current_price == null) return 'sem preço atual'
  return new Intl.NumberFormat('pt-BR', {
    style: 'currency',
    currency: asset.currency,
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(asset.current_price)
}

export default function ManualPriceModal({ asset, onClose, onSaved }: Props) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [raw, setRaw] = useState<string>(
    asset.current_price != null ? String(asset.current_price) : '',
  )
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  // Focus the input on open
  useEffect(() => {
    inputRef.current?.focus()
    inputRef.current?.select()
  }, [])

  // ESC closes; ⌘↵ / Ctrl↵ submits
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        e.preventDefault()
        onClose()
      } else if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
        e.preventDefault()
        submit()
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [raw, note])

  function parsePrice(s: string): number | null {
    // Accept either "850000.00" or "850000,00"
    const normalized = s.replace(/\./g, '').replace(',', '.').trim()
    if (!normalized) return null
    const n = Number(normalized)
    if (!Number.isFinite(n) || n < 0) return null
    return n
  }

  async function submit() {
    if (busy) return
    const value = parsePrice(raw)
    if (value === null) {
      setErr('Informe um número ≥ 0.')
      return
    }
    setBusy(true)
    setErr(null)
    try {
      const result = await api.updateAssetPrice(
        asset.id,
        value.toFixed(2),
        note.trim() || undefined,
      )
      onSaved(result)
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Erro')
    } finally {
      setBusy(false)
    }
  }

  const ccySymbol = asset.currency === 'USD' ? 'US$' : 'R$'

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label="Editar preço manualmente"
    >
      <div
        className="w-[420px] max-w-[92vw] rounded-xl bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 shadow-2xl p-5"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="text-[13px] font-semibold text-gray-900 dark:text-gray-100">
          Editar preço · {asset.ticker ?? asset.name}
        </div>

        <div className="mt-3 text-[11px] text-gray-500 dark:text-gray-400">
          Preço atual: <span className="tnum text-gray-700 dark:text-gray-300">{fmtCurrent(asset)}</span>
          {asset.price_updated_at && (
            <> · atualizado {formatRelative(asset.price_updated_at)}</>
          )}
        </div>

        <label className="block mt-4">
          <span className="text-[11px] uppercase tracking-wider font-medium text-gray-500 dark:text-gray-400">
            Novo preço
          </span>
          <div className="mt-1 flex items-center gap-2 rounded-lg border border-gray-300 dark:border-gray-700 px-2 focus-within:border-indigo-500">
            <span className="text-[12px] text-gray-500">{ccySymbol}</span>
            <input
              ref={inputRef}
              type="text"
              inputMode="decimal"
              value={raw}
              onChange={(e) => { setRaw(e.target.value); setErr(null) }}
              placeholder="0,00"
              className="flex-1 h-9 bg-transparent text-[13px] tnum outline-none"
              aria-label="Novo preço"
            />
          </div>
        </label>

        <label className="block mt-3">
          <span className="text-[11px] uppercase tracking-wider font-medium text-gray-500 dark:text-gray-400">
            Notas (opcional)
          </span>
          <textarea
            value={note}
            onChange={(e) => setNote(e.target.value)}
            rows={2}
            placeholder="Avaliação anual feita por..."
            className="mt-1 w-full rounded-lg border border-gray-300 dark:border-gray-700 bg-transparent px-2 py-1.5 text-[12px] outline-none focus:border-indigo-500"
          />
        </label>

        {err && (
          <div className="mt-3 text-[11px] text-red-500 dark:text-red-400">{err}</div>
        )}

        <div className="mt-5 flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="h-8 px-3 inline-flex items-center rounded-lg text-[12px] text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
          >
            Cancelar
          </button>
          <button
            type="button"
            onClick={submit}
            disabled={busy}
            className="h-8 px-3 inline-flex items-center gap-1.5 rounded-lg text-[12px] bg-indigo-500 hover:bg-indigo-400 disabled:opacity-50 text-white transition-colors"
          >
            {busy ? 'Salvando…' : 'Salvar'}
            <kbd className="text-[10px] opacity-70 ml-1">⌘↵</kbd>
          </button>
        </div>
      </div>
    </div>
  )
}
