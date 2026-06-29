import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Plus, Trash2 } from 'lucide-react'

import AppLayout from '../../components/AppLayout'
import { Card, PageHeader } from '../../components/ui'
import {
  api,
  type TargetAllocationOut,
  type TargetDimension,
  type TargetEntryIn,
  type UserOut,
} from '../../lib/api'
import { KLASS, type CollapsedClassCode } from '../../lib/tokens'
import { useEscapeKey } from '../../lib/useEscapeKey'

type DraftRow = { id: string; key: string; pct: string }

interface DimensionDraft {
  rows: DraftRow[]
  dirty: boolean
}

const CLASS_KEYS: CollapsedClassCode[] = [
  'STOCK',
  'REIT',
  'ETF',
  'FIXED_INCOME',
  'FUND',
  'CRYPTO',
  'PRIVATE_PENSION',
  'FGTS',
  'CASH',
  'REAL_ESTATE',
  'VEHICLE',
  'OPTION',
]

const COUNTRY_KEYS: { code: string; label: string; flag: string }[] = [
  { code: 'BR', label: 'Brasil', flag: '🇧🇷' },
  { code: 'US', label: 'EUA', flag: '🇺🇸' },
]

const CLASS_PRESET: Record<string, string> = {
  STOCK: '30',
  FIXED_INCOME: '25',
  REIT: '20',
  ETF: '10',
  CRYPTO: '5',
  PRIVATE_PENSION: '5',
  FUND: '5',
}

const COUNTRY_PRESET: Record<string, string> = {
  BR: '70',
  US: '30',
}

function newRowId(): string {
  return Math.random().toString(36).slice(2, 10)
}

function entriesFromApi(
  entries: { key: string; target_pct: string }[],
): DraftRow[] {
  return entries.map((e) => ({
    id: newRowId(),
    key: e.key,
    pct: (Number(e.target_pct) * 100).toFixed(2).replace(/\.?0+$/, '') || '0',
  }))
}

function sumPct(rows: DraftRow[]): number {
  return rows.reduce((acc, r) => acc + (Number(r.pct) || 0), 0)
}

function labelForClass(key: string): string {
  return KLASS[key as CollapsedClassCode]?.label ?? key
}

function colorForClass(key: string): string {
  return KLASS[key as CollapsedClassCode]?.color ?? '#9ca3af'
}

function labelForCountry(key: string): string {
  return COUNTRY_KEYS.find((c) => c.code === key)?.label ?? key
}

function flagForCountry(key: string): string {
  return COUNTRY_KEYS.find((c) => c.code === key)?.flag ?? '🌐'
}

export default function TargetAllocation() {
  const navigate = useNavigate()
  const [me, setMe] = useState<UserOut | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [toast, setToast] = useState('')
  const [tab, setTab] = useState<TargetDimension>('CLASS')
  const [classDraft, setClassDraft] = useState<DimensionDraft>({
    rows: [],
    dirty: false,
  })
  const [countryDraft, setCountryDraft] = useState<DimensionDraft>({
    rows: [],
    dirty: false,
  })
  const [confirmOpen, setConfirmOpen] = useState(false)

  useEscapeKey(() => {
    if (confirmOpen) setConfirmOpen(false)
  })

  useEffect(() => {
    api.me().then(setMe).catch(() => navigate('/login'))
  }, [navigate])

  useEffect(() => {
    if (!me || !me.workspace_id) return
    setLoading(true)
    setError('')
    api
      .getTargetAllocation(me.workspace_id)
      .then((data: TargetAllocationOut) => {
        setClassDraft({ rows: entriesFromApi(data.CLASS.entries), dirty: false })
        setCountryDraft({
          rows: entriesFromApi(data.COUNTRY.entries),
          dirty: false,
        })
      })
      .catch((e: unknown) =>
        setError(e instanceof Error ? e.message : 'Erro ao carregar.'),
      )
      .finally(() => setLoading(false))
  }, [me])

  const currentDraft = tab === 'CLASS' ? classDraft : countryDraft
  const setCurrentDraft = tab === 'CLASS' ? setClassDraft : setCountryDraft
  const availableKeys = useMemo(() => {
    if (tab === 'CLASS') {
      const used = new Set(classDraft.rows.map((r) => r.key))
      return CLASS_KEYS.filter((k) => !used.has(k))
    }
    const used = new Set(countryDraft.rows.map((r) => r.key))
    return COUNTRY_KEYS.map((c) => c.code).filter((k) => !used.has(k))
  }, [tab, classDraft.rows, countryDraft.rows])

  const total = sumPct(currentDraft.rows)
  const totalRounded = Math.round(total * 100) / 100
  const isValidSum = Math.abs(totalRounded - 100) <= 0.01
  const canSubmit =
    currentDraft.dirty &&
    isValidSum &&
    currentDraft.rows.every((r) => r.key && r.pct !== '')

  function updateRow(id: string, patch: Partial<DraftRow>) {
    setCurrentDraft({
      rows: currentDraft.rows.map((r) => (r.id === id ? { ...r, ...patch } : r)),
      dirty: true,
    })
  }

  function addRow() {
    const nextKey = availableKeys[0]
    if (!nextKey) return
    setCurrentDraft({
      rows: [...currentDraft.rows, { id: newRowId(), key: nextKey, pct: '0' }],
      dirty: true,
    })
  }

  function removeRow(id: string) {
    setCurrentDraft({
      rows: currentDraft.rows.filter((r) => r.id !== id),
      dirty: true,
    })
  }

  function distributeEqually() {
    if (currentDraft.rows.length === 0) return
    const each = (100 / currentDraft.rows.length).toFixed(2)
    setCurrentDraft({
      rows: currentDraft.rows.map((r) => ({ ...r, pct: each })),
      dirty: true,
    })
  }

  function restoreDefault() {
    const preset = tab === 'CLASS' ? CLASS_PRESET : COUNTRY_PRESET
    setCurrentDraft({
      rows: Object.entries(preset).map(([key, pct]) => ({
        id: newRowId(),
        key,
        pct,
      })),
      dirty: true,
    })
  }

  async function performSave() {
    if (!me || !me.workspace_id) return
    setSaving(true)
    setError('')
    const entries: TargetEntryIn[] = currentDraft.rows.map((r) => ({
      key: r.key,
      target_pct: (Number(r.pct) / 100).toFixed(4),
    }))
    try {
      const data = await api.putTargetAllocation(me.workspace_id, tab, entries)
      if (tab === 'CLASS') {
        setClassDraft({ rows: entriesFromApi(data.CLASS.entries), dirty: false })
      } else {
        setCountryDraft({
          rows: entriesFromApi(data.COUNTRY.entries),
          dirty: false,
        })
      }
      setToast(`Alocação alvo (${tab === 'CLASS' ? 'classe' : 'país'}) salva.`)
      window.setTimeout(() => setToast(''), 2500)
      setConfirmOpen(false)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Erro ao salvar.')
    } finally {
      setSaving(false)
    }
  }

  if (!me) return null

  const labelFor = tab === 'CLASS' ? labelForClass : labelForCountry
  const colorFor = tab === 'CLASS' ? colorForClass : () => '#9ca3af'
  const prefixFor = tab === 'COUNTRY' ? flagForCountry : null

  return (
    <AppLayout user={me}>
      <div className="space-y-6">
        <PageHeader
          title="Alocação alvo"
        />
        <p className="text-[13px] text-gray-500 dark:text-gray-400 -mt-2">
          Defina as metas de alocação do seu portfólio por classe de ativo e por
          país. Usadas pelo Suporte à Decisão pra calcular gap vs atual e como
          restrições da otimização (Markowitz).
        </p>

        <Card padding="p-0">
          <div className="border-b border-gray-200 dark:border-gray-800 flex items-center gap-1 px-2">
            {(['CLASS', 'COUNTRY'] as const).map((d) => (
              <button
                key={d}
                onClick={() => setTab(d)}
                className={`px-4 py-3 text-[13px] font-medium border-b-2 -mb-px transition-colors ${
                  tab === d
                    ? 'border-indigo-500 text-indigo-700 dark:text-indigo-300'
                    : 'border-transparent text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300'
                }`}
              >
                {d === 'CLASS' ? 'Por classe' : 'Por país'}
              </button>
            ))}
          </div>

          {loading ? (
            <div className="p-12 text-center text-sm text-gray-400 dark:text-gray-600">
              Carregando…
            </div>
          ) : (
            <div className="p-5 space-y-4">
              {error && (
                <div
                  data-testid="ta-error"
                  className="rounded-lg border border-red-200 dark:border-red-900 bg-red-50 dark:bg-red-900/20 p-3 text-[13px] text-red-700 dark:text-red-300"
                >
                  {error}
                </div>
              )}
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-200 dark:border-gray-800 text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400">
                    <th className="text-left py-2 font-medium w-1/2">Item</th>
                    <th className="text-right py-2 font-medium">Meta (%)</th>
                    <th className="w-10"></th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
                  {currentDraft.rows.length === 0 && (
                    <tr>
                      <td colSpan={3} className="py-8 text-center text-xs text-gray-400 dark:text-gray-600">
                        Nenhuma meta cadastrada. Clique em "Adicionar" ou "Restaurar padrão".
                      </td>
                    </tr>
                  )}
                  {currentDraft.rows.map((row) => (
                    <tr key={row.id} className="hover:bg-gray-50 dark:hover:bg-gray-800/40">
                      <td className="py-2">
                        <div className="flex items-center gap-2">
                          {tab === 'CLASS' ? (
                            <span
                              className="inline-block w-2.5 h-2.5 rounded-full"
                              style={{ background: colorFor(row.key) }}
                            />
                          ) : (
                            <span className="text-base leading-none">
                              {prefixFor ? prefixFor(row.key) : ''}
                            </span>
                          )}
                          <select
                            value={row.key}
                            onChange={(e) => updateRow(row.id, { key: e.target.value })}
                            className="h-8 px-2 text-[13px] rounded-md border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 text-gray-700 dark:text-gray-200 focus:outline-none focus:border-indigo-500"
                          >
                            <option value={row.key}>{labelFor(row.key)}</option>
                            {availableKeys.map((k) => (
                              <option key={k} value={k}>{labelFor(k)}</option>
                            ))}
                          </select>
                        </div>
                      </td>
                      <td className="py-2 text-right">
                        <input
                          type="number"
                          step="0.01"
                          min="0"
                          max="100"
                          value={row.pct}
                          onChange={(e) => updateRow(row.id, { pct: e.target.value })}
                          className="w-28 h-8 px-2 text-right text-[13px] tnum rounded-md border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 text-gray-700 dark:text-gray-200 focus:outline-none focus:border-indigo-500"
                          aria-label={`Meta de ${labelFor(row.key)}`}
                        />
                      </td>
                      <td className="py-2 text-right pr-1">
                        <button
                          onClick={() => removeRow(row.id)}
                          aria-label="Remover linha"
                          className="text-gray-400 hover:text-red-500 transition-colors p-1"
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr className="border-t border-gray-200 dark:border-gray-800">
                    <td className="py-3 text-[13px] font-medium text-gray-700 dark:text-gray-300">
                      Soma
                    </td>
                    <td className="py-3 text-right">
                      <span
                        data-testid="ta-sum"
                        className={`inline-flex items-center px-2 py-0.5 rounded-full text-[12px] font-semibold tnum ${
                          isValidSum
                            ? 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300'
                            : 'bg-red-500/15 text-red-700 dark:text-red-300'
                        }`}
                      >
                        {totalRounded.toFixed(2)}%
                      </span>
                    </td>
                    <td></td>
                  </tr>
                </tfoot>
              </table>

              <div className="flex flex-wrap items-center justify-between gap-3 pt-3">
                <div className="flex flex-wrap gap-2">
                  <button
                    onClick={addRow}
                    disabled={availableKeys.length === 0}
                    className="inline-flex items-center gap-1.5 h-8 px-3 text-[12px] rounded-md bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700 disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    <Plus className="w-3.5 h-3.5" /> Adicionar
                  </button>
                  <button
                    onClick={distributeEqually}
                    className="h-8 px-3 text-[12px] rounded-md bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700"
                  >
                    Distribuir igualmente
                  </button>
                  <button
                    onClick={restoreDefault}
                    className="h-8 px-3 text-[12px] rounded-md bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700"
                  >
                    Restaurar padrão
                  </button>
                </div>
                <button
                  data-testid="ta-save"
                  onClick={() => setConfirmOpen(true)}
                  disabled={!canSubmit || saving}
                  className="h-8 px-4 text-[12px] font-medium rounded-md bg-indigo-500 text-white hover:bg-indigo-400 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {saving ? 'Salvando…' : 'Salvar metas'}
                </button>
              </div>
            </div>
          )}
        </Card>
      </div>

      {confirmOpen && (
        <div
          data-testid="ta-confirm"
          className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4"
          onClick={() => setConfirmOpen(false)}
        >
          <div
            className="bg-white dark:bg-gray-900 rounded-xl shadow-xl border border-gray-200 dark:border-gray-800 max-w-md w-full p-5"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="text-base font-semibold mb-2">
              Confirmar salvamento
            </h3>
            <p className="text-[13px] text-gray-600 dark:text-gray-400 mb-4">
              Vai substituir todas as metas {tab === 'CLASS' ? 'por classe' : 'por país'}{' '}
              do workspace pelas {currentDraft.rows.length} entradas configuradas.
            </p>
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setConfirmOpen(false)}
                disabled={saving}
                className="h-8 px-3 text-[12px] rounded-md bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700"
              >
                Cancelar
              </button>
              <button
                onClick={performSave}
                disabled={saving}
                className="h-8 px-3 text-[12px] font-medium rounded-md bg-indigo-500 text-white hover:bg-indigo-400 disabled:opacity-50"
              >
                {saving ? 'Salvando…' : 'Confirmar'}
              </button>
            </div>
          </div>
        </div>
      )}

      {toast && (
        <div className="fixed bottom-6 right-6 z-50 px-3 py-2 rounded-lg bg-gray-900 dark:bg-gray-100 text-white dark:text-gray-900 text-[12px] shadow-lg">
          {toast}
        </div>
      )}
    </AppLayout>
  )
}
