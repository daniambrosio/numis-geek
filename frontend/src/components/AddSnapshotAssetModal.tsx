/* Spec 49 hotfix #12 — manually add an asset to an IN_REVIEW snapshot.
 *
 * Triggered by "+ Adicionar ativo" on the SnapshotDetail header. Filters
 * out assets already in the snapshot (the obvious duplicate guard the
 * user asked for). Backend re-validates workspace/active/duplicate. */
import { useEffect, useMemo, useState } from 'react'
import { Plus, X } from 'lucide-react'

import { api, type AssetOut, type SnapshotItemOut } from '../lib/api'
import { useEscapeKey } from '../lib/useEscapeKey'

interface Props {
  snapshotId: string
  existingAssetIds: Set<string>
  assets: AssetOut[]
  onAdded: (item: SnapshotItemOut) => void
  onClose: () => void
}

export default function AddSnapshotAssetModal({
  snapshotId, existingAssetIds, assets, onAdded, onClose,
}: Props) {
  useEscapeKey(onClose)

  const candidates = useMemo(
    () =>
      [...assets]
        .filter(a => a.is_active && !existingAssetIds.has(a.id))
        .sort((a, b) =>
          (a.ticker ?? a.name).toLocaleLowerCase('pt-BR').localeCompare(
            (b.ticker ?? b.name).toLocaleLowerCase('pt-BR'),
            'pt-BR',
          )),
    [assets, existingAssetIds],
  )

  const [search, setSearch] = useState('')
  const [picked, setPicked] = useState<string>('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    if (!picked && candidates.length > 0) setPicked(candidates[0].id)
  }, [candidates, picked])

  const filtered = useMemo(() => {
    const q = search.trim().toLocaleLowerCase('pt-BR')
    if (!q) return candidates
    return candidates.filter(a =>
      (a.ticker ?? '').toLocaleLowerCase('pt-BR').includes(q)
      || a.name.toLocaleLowerCase('pt-BR').includes(q),
    )
  }, [candidates, search])

  useEffect(() => {
    if (filtered.length && !filtered.some(a => a.id === picked)) {
      setPicked(filtered[0].id)
    }
  }, [filtered, picked])

  async function submit() {
    if (busy || !picked) return
    setBusy(true); setErr(null)
    try {
      const item = await api.addSnapshotItem(snapshotId, picked)
      onAdded(item)
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Erro')
      setBusy(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center bg-black/60 p-4"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
    >
      <div
        className="w-full max-w-lg bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-700 shadow-2xl flex flex-col max-h-[85vh]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="px-5 py-3 border-b border-gray-200 dark:border-gray-800 flex items-center justify-between">
          <div className="text-sm font-semibold">Adicionar ativo ao fechamento</div>
          <button
            onClick={onClose}
            className="w-7 h-7 inline-flex items-center justify-center rounded-md text-gray-400 hover:text-gray-700 dark:hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800"
            aria-label="Fechar"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="p-5 space-y-4 overflow-y-auto">
          <div className="text-[11px] text-gray-500 dark:text-gray-400">
            O ativo entra com o valor calculado pela posição atual.
            Você pode editar o saldo no item depois.
          </div>

          <label className="block">
            <span className="text-[11px] uppercase tracking-wider font-medium text-gray-500">
              Buscar
            </span>
            <input
              autoFocus
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="ticker ou nome"
              className="mt-1 w-full h-9 px-3 text-[13px] rounded-lg bg-gray-50 dark:bg-gray-800/50 border border-gray-200 dark:border-gray-800 focus:outline-none focus:border-indigo-500"
              data-testid="add-snapshot-asset-search"
            />
          </label>

          <label className="block">
            <span className="text-[11px] uppercase tracking-wider font-medium text-gray-500">
              Ativo ({filtered.length} disponível{filtered.length === 1 ? '' : 'is'})
            </span>
            <select
              value={picked}
              onChange={e => setPicked(e.target.value)}
              size={Math.min(8, Math.max(3, filtered.length))}
              className="mt-1 w-full text-[13px] rounded-lg bg-gray-50 dark:bg-gray-800/50 border border-gray-200 dark:border-gray-800 focus:outline-none focus:border-indigo-500"
              data-testid="add-snapshot-asset-select"
            >
              {filtered.length === 0 && (
                <option value="">Nenhum ativo disponível</option>
              )}
              {filtered.map(a => (
                <option key={a.id} value={a.id}>
                  {a.ticker ? `${a.ticker} · ` : ''}{a.name}
                </option>
              ))}
            </select>
          </label>

          {err && (
            <div className="text-[11px] text-red-600 dark:text-red-400">{err}</div>
          )}
        </div>

        <div className="px-5 py-3 border-t border-gray-200 dark:border-gray-800 flex items-center justify-end gap-2">
          <button
            onClick={onClose}
            disabled={busy}
            className="h-8 px-3 inline-flex items-center gap-1.5 rounded-lg text-[12px] bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700 disabled:opacity-50"
          >
            Cancelar
          </button>
          <button
            onClick={() => void submit()}
            disabled={busy || !picked}
            className="h-9 px-4 inline-flex items-center gap-1.5 rounded-lg text-[13px] font-medium bg-indigo-500 hover:bg-indigo-400 disabled:opacity-50 disabled:cursor-not-allowed text-white"
            data-testid="add-snapshot-asset-submit"
          >
            <Plus className="w-3.5 h-3.5" />
            {busy ? 'Adicionando…' : 'Adicionar'}
          </button>
        </div>
      </div>
    </div>
  )
}
