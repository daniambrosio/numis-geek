/* Spec 49 hotfix #10 — inline edit of a snapshot item.
 *
 * Triggered by clicking a row in the "Posições Congeladas" table on
 * /snapshots/{ym}. Lets the user fix the price (typed as TOTAL or
 * per-UNIT) without leaving the snapshot context. */
import { useEffect, useRef, useState } from 'react'
import { ExternalLink, Trash2, X } from 'lucide-react'
import { Link } from 'react-router-dom'

import {
  api,
  type AssetOut,
  type SnapshotItemOut,
} from '../lib/api'

interface Props {
  snapshotId: string
  ym: string
  item: SnapshotItemOut
  asset: AssetOut
  /** PTAX USD/BRL do snapshot (snap.fx_rate_usd_brl). Usado pra exibir
   *  a conversão BRL ↔ USD no preview enquanto o user digita. */
  fxRate?: number | null
  onSaved: (updated: SnapshotItemOut) => void
  onDeleted: (asset_id: string) => void
  onClose: () => void
}

const TOTAL_CLASSES = new Set([
  'FIXED_INCOME', 'FUND', 'REAL_ESTATE', 'VEHICLE',
  'PRIVATE_PENSION', 'CASH',
])

function fmtNumber(n: number, decimals = 2): string {
  return n.toLocaleString('pt-BR', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })
}

export default function SnapshotItemEditModal({
  snapshotId, ym, item, asset, fxRate, onSaved, onDeleted, onClose,
}: Props) {
  const defaultMode: 'unit' | 'total' =
    asset.asset_class && TOTAL_CLASSES.has(asset.asset_class) ? 'total' : 'unit'
  const qty = Number(item.quantity)
  const currentUnit = item.unit_price ? Number(item.unit_price) : null
  const currentTotal = item.market_value_native
    ? Number(item.market_value_native)
    : (currentUnit != null ? currentUnit * qty : null)

  const initialValue =
    defaultMode === 'total' && currentTotal != null
      ? currentTotal.toFixed(2).replace('.', ',')
      : currentUnit != null
        ? currentUnit.toFixed(2).replace('.', ',')
        : ''
  const [mode, setMode] = useState<'unit' | 'total'>(defaultMode)
  const [raw, setRaw] = useState<string>(initialValue)
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    inputRef.current?.focus()
    inputRef.current?.select()
  }, [])

  // ESC closes, ⌘↵ submits.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') { e.preventDefault(); onClose() }
      else if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
        e.preventDefault(); void submit()
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [raw, mode, note])

  function parsePrice(s: string): number | null {
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
    setBusy(true); setErr(null)
    try {
      const updated = await api.patchSnapshotItem(snapshotId, asset.id, {
        price: value.toFixed(2),
        value_mode: mode,
        note: note.trim() || null,
      })
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
      await api.deleteSnapshotItem(snapshotId, asset.id)
      onDeleted(asset.id)
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Erro')
      setBusy(false)
      setConfirmDelete(false)
    }
  }

  // Preview of what will be stored.
  const parsed = parsePrice(raw)
  let previewUnit: number | null = null
  let previewTotal: number | null = null
  if (parsed != null) {
    if (mode === 'total') {
      previewTotal = parsed
      previewUnit = qty > 0 ? parsed / qty : parsed
    } else {
      previewUnit = parsed
      previewTotal = parsed * qty
    }
  }

  const ccySymbol = asset.currency === 'USD' ? 'US$' : 'R$'

  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center bg-black/60 p-4"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
    >
      <div
        className="w-full max-w-md bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-700 shadow-2xl flex flex-col max-h-[90vh]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="px-5 py-3 border-b border-gray-200 dark:border-gray-800 flex items-center justify-between">
          <div className="min-w-0">
            <div className="text-sm font-semibold truncate">
              {asset.ticker || asset.name}
            </div>
            <div className="text-[10px] text-gray-500 truncate flex items-center gap-1">
              Fechamento {ym} · <Link
                to={`/assets/${asset.id}`}
                state={{ from: `/snapshots/${ym}`, fromLabel: `Fechamento ${ym}` }}
                className="inline-flex items-center gap-0.5 text-indigo-500 hover:text-indigo-300"
                title="Abrir página do ativo"
              >
                ver ativo <ExternalLink className="w-2.5 h-2.5" />
              </Link>
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

        <div className="p-5 space-y-4">
          <div className="text-[11px] text-gray-500 grid grid-cols-2 gap-2">
            <div>
              <div className="uppercase tracking-wider font-semibold">Qtd</div>
              <div className="tnum text-gray-700 dark:text-gray-300 text-[13px]">{fmtNumber(qty, 4)}</div>
            </div>
            <div>
              <div className="uppercase tracking-wider font-semibold">Valor atual</div>
              <div className="tnum text-gray-700 dark:text-gray-300 text-[13px]">
                {currentTotal != null ? `${ccySymbol} ${fmtNumber(currentTotal)}` : '—'}
              </div>
            </div>
          </div>

          <div>
            <div className="text-[11px] uppercase tracking-wider font-medium text-gray-500 mb-1">
              Modo de entrada
            </div>
            <div className="inline-flex rounded-lg border border-gray-300 dark:border-gray-700 overflow-hidden text-[12px]">
              <button
                onClick={() => setMode('unit')}
                className={`px-3 py-1.5 ${mode === 'unit' ? 'bg-indigo-500 text-white' : 'bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-300'}`}
                data-testid="snapshot-item-mode-unit"
              >
                Preço unitário
              </button>
              <button
                onClick={() => setMode('total')}
                className={`px-3 py-1.5 ${mode === 'total' ? 'bg-indigo-500 text-white' : 'bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-300'}`}
                data-testid="snapshot-item-mode-total"
              >
                Valor total
              </button>
            </div>
            <div className="text-[10px] text-gray-500 mt-1">
              {mode === 'total'
                ? 'Você digita o valor consolidado (default pra fundo/RF/imóvel/veículo).'
                : 'Você digita o preço por unidade/cota (default pra ações/ETF/REIT).'}
            </div>
          </div>

          <label className="block">
            <span className="text-[11px] uppercase tracking-wider font-medium text-gray-500">
              {mode === 'total' ? 'Valor total' : 'Preço unitário'}
            </span>
            <div className="mt-1 flex items-center gap-2 rounded-lg border border-gray-300 dark:border-gray-700 px-2 focus-within:border-indigo-500">
              <span className="text-[12px] text-gray-500">{ccySymbol}</span>
              <input
                ref={inputRef}
                type="text"
                inputMode="decimal"
                value={raw}
                onChange={e => { setRaw(e.target.value); setErr(null) }}
                placeholder="0,00"
                className="flex-1 h-9 bg-transparent text-[14px] tnum outline-none"
                data-testid="snapshot-item-price-input"
              />
            </div>
          </label>

          {previewUnit != null && previewTotal != null && (
            <div className="rounded-lg bg-gray-50 dark:bg-gray-800/40 border border-gray-200 dark:border-gray-800 px-3 py-2 text-[11px] text-gray-600 dark:text-gray-300 space-y-1">
              <div className="grid grid-cols-2 gap-2">
                <div>
                  Preço unitário: <span className="tnum font-medium">{ccySymbol} {fmtNumber(previewUnit, mode === 'total' ? 4 : 2)}</span>
                </div>
                <div>
                  Valor total: <span className="tnum font-medium">{ccySymbol} {fmtNumber(previewTotal)}</span>
                </div>
              </div>
              {asset.currency === 'USD' && fxRate && fxRate > 0 && (
                <div className="text-[10px] text-gray-500 dark:text-gray-400">
                  ≈ <span className="tnum font-medium">R$ {fmtNumber(previewTotal * fxRate)}</span>
                  {' '}<span className="text-gray-400">(PTAX {fxRate.toFixed(4)})</span>
                </div>
              )}
            </div>
          )}

          <label className="block">
            <span className="text-[11px] uppercase tracking-wider font-medium text-gray-500">
              Notas (opcional)
            </span>
            <textarea
              value={note}
              onChange={e => setNote(e.target.value)}
              rows={2}
              placeholder="ex: corrigi valor lendo o extrato XP"
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
                <span className="text-[11px] text-red-600 dark:text-red-400">
                  Remover do fechamento?
                </span>
                <button
                  onClick={() => void handleDelete()}
                  disabled={busy}
                  className="h-8 px-3 inline-flex items-center gap-1.5 rounded-lg text-[12px] bg-red-600 hover:bg-red-500 text-white disabled:opacity-50"
                  data-testid="snapshot-item-delete-confirm"
                >
                  {busy ? 'Removendo…' : 'Sim, remover'}
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
                title="Remover este ativo do fechamento"
                className="h-8 w-8 inline-flex items-center justify-center rounded-lg text-gray-500 hover:text-red-500 hover:bg-red-500/10 disabled:opacity-50"
                data-testid="snapshot-item-delete"
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
              disabled={busy || parsed == null || confirmDelete}
              className="h-9 px-4 inline-flex items-center gap-1.5 rounded-lg text-[13px] font-medium bg-emerald-500 hover:bg-emerald-400 disabled:opacity-50 disabled:cursor-not-allowed text-white"
              data-testid="snapshot-item-save"
            >
              {busy ? 'Salvando…' : 'Salvar'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
