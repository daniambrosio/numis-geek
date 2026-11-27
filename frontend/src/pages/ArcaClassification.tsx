/* Spec 85 — classificação ARCA dos ativos: letra/subcategoria efetiva,
 * origem (automática, manual, sem classificação), edição inline e em lote. */
import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import AppLayout from '../components/AppLayout'
import { Card, PageHeader } from '../components/ui'
import {
  api,
  type ArcaAssetOut,
  type ArcaCategory,
  type ArcaClassificationItem,
  type ArcaSummaryOut,
  type UserOut,
} from '../lib/api'
import { ARCA_LETTER_LABEL, ARCA_LETTERS, ARCA_SUBS, ARCA_SUB_LABEL, arcaParent } from '../lib/arca'
import { fmtBRL } from '../lib/money'

const CATEGORY_OPTIONS: ArcaCategory[] = [...ARCA_LETTERS, 'OUT_OF_SCOPE']

const SOURCE_BADGE: Record<string, { label: string; cls: string }> = {
  derived: { label: 'auto', cls: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400' },
  manual: { label: 'manual', cls: 'bg-indigo-50 text-indigo-700 dark:bg-indigo-900/30 dark:text-indigo-300' },
  unmapped: { label: 'sem classificação', cls: 'bg-amber-50 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300' },
}

function isPending(a: ArcaAssetOut): boolean {
  return a.category == null || (a.category !== 'OUT_OF_SCOPE' && a.subcategory == null)
}

export default function ArcaClassification() {
  const navigate = useNavigate()
  const [me, setMe] = useState<UserOut | null>(null)
  const [data, setData] = useState<ArcaSummaryOut | null>(null)
  const [error, setError] = useState('')
  const [onlyPending, setOnlyPending] = useState(
    () => new URLSearchParams(window.location.search).get('pending') === '1',
  )
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [bulkCat, setBulkCat] = useState<string>('')
  const [bulkSub, setBulkSub] = useState<string>('')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    api.me().then(setMe).catch(() => navigate('/login'))
  }, [navigate])

  useEffect(() => {
    if (!me || !me.workspace_id) return
    api.getArcaSummary(me.workspace_id)
      .then(setData)
      .catch((e) => setError(e instanceof Error ? e.message : 'Erro ao carregar.'))
  }, [me])

  const rows = useMemo(
    () => (data?.assets ?? []).filter((a) => !onlyPending || isPending(a)),
    [data, onlyPending],
  )

  async function apply(items: ArcaClassificationItem[]) {
    if (!me?.workspace_id) return
    setSaving(true)
    setError('')
    try {
      setData(await api.putArcaClassification(me.workspace_id, items))
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Erro ao salvar.')
    } finally {
      setSaving(false)
    }
  }

  function onCategory(a: ArcaAssetOut, v: string) {
    if (v === '') return apply([{ asset_id: a.asset_id, category: null, subcategory: null }])
    const cat = v as ArcaCategory
    const keepSub = a.subcategory && arcaParent(a.subcategory) === cat ? a.subcategory : null
    return apply([{ asset_id: a.asset_id, category: cat, subcategory: keepSub }])
  }

  function onSub(a: ArcaAssetOut, v: string) {
    return apply([{
      asset_id: a.asset_id,
      category: (a.category ?? arcaParent(v)) as ArcaCategory | null,
      subcategory: v || null,
    }])
  }

  async function applyBulk() {
    if (selected.size === 0) return
    const items = [...selected].map((id) => ({
      asset_id: id,
      category: bulkCat === '' ? null : (bulkCat as ArcaCategory),
      subcategory: bulkSub || null,
    }))
    await apply(items)
    setSelected(new Set())
  }

  if (!me) return null
  const select = 'h-7 rounded-md border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-900 px-1.5 text-[12px]'
  const bulkSubs = bulkCat && bulkCat !== 'OUT_OF_SCOPE' ? ARCA_SUBS[bulkCat as keyof typeof ARCA_SUBS] : []

  return (
    <AppLayout user={me}>
      <div className="space-y-6">
        <PageHeader title="Classificação ARCA" countLabel="ativos" count={rows.length} />
        <p className="text-[13px] text-gray-500 dark:text-gray-400 -mt-2 max-w-3xl">
          Cada ativo vai para uma letra da ARCA e, se possível, para uma
          subcategoria. "auto" vem da classe, do indexador e do país; a
          subcategoria de ações e FIIs vem de uma lista de tickers conhecidos, do
          setor nos fundamentos ou do nome do fundo (o motivo aparece ao lado). O
          que você escolhe aqui vira "manual" e vale por cima; "Automático" no
          select volta para a regra.{' '}
          <a className="underline" href="/decision-support">Voltar ao Suporte à Decisão</a>
        </p>

        {error && (
          <div className="rounded-lg border border-red-200 dark:border-red-900 bg-red-50 dark:bg-red-900/20 p-3 text-[13px] text-red-700 dark:text-red-300">
            {error}
          </div>
        )}

        <Card>
          <div className="flex flex-wrap items-center gap-3 mb-3">
            <label className="flex items-center gap-1.5 text-[12px] text-gray-700 dark:text-gray-300">
              <input
                type="checkbox"
                data-testid="arca-only-pending"
                checked={onlyPending}
                onChange={(e) => setOnlyPending(e.target.checked)}
              />
              Só pendentes
            </label>
            {selected.size > 0 && (
              <div className="flex flex-wrap items-center gap-2 text-[12px]" data-testid="arca-bulk">
                <span>{selected.size} selecionado(s):</span>
                <select className={select} value={bulkCat} onChange={(e) => { setBulkCat(e.target.value); setBulkSub('') }}>
                  <option value="">Automático</option>
                  {CATEGORY_OPTIONS.map((c) => <option key={c} value={c}>{ARCA_LETTER_LABEL[c]}</option>)}
                </select>
                {bulkSubs.length > 0 && (
                  <select className={select} value={bulkSub} onChange={(e) => setBulkSub(e.target.value)}>
                    <option value="">Sem subcategoria</option>
                    {bulkSubs.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
                  </select>
                )}
                <button
                  type="button"
                  data-testid="arca-bulk-apply"
                  disabled={saving}
                  onClick={applyBulk}
                  className="h-7 px-3 rounded-md bg-indigo-500 text-white font-medium disabled:opacity-50"
                >
                  Aplicar
                </button>
              </div>
            )}
          </div>

          {!data ? (
            <div className="text-[12px] text-gray-500 py-6 text-center">Carregando…</div>
          ) : rows.length === 0 ? (
            <div className="text-[12px] text-gray-500 py-6 text-center">Nada pendente. 🎉</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-[12px] min-w-[720px]">
                <thead>
                  <tr className="border-b border-gray-200 dark:border-gray-800 text-[10px] uppercase tracking-wider text-gray-500 dark:text-gray-400">
                    <th className="w-6"></th>
                    <th className="text-left py-1.5 font-medium">Ativo</th>
                    <th className="text-left py-1.5 font-medium">Classe</th>
                    <th className="text-right py-1.5 font-medium">Valor</th>
                    <th className="text-left py-1.5 pl-4 font-medium">Letra</th>
                    <th className="text-left py-1.5 font-medium">Subcategoria</th>
                    <th className="text-left py-1.5 font-medium">Origem</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
                  {rows.map((a) => {
                    const subs = a.category && a.category !== 'OUT_OF_SCOPE' ? ARCA_SUBS[a.category] : []
                    const badge = SOURCE_BADGE[a.source]
                    return (
                      <tr key={a.asset_id} data-testid={`arca-row-${a.asset_id}`}>
                        <td>
                          <input
                            type="checkbox"
                            aria-label={`selecionar ${a.ticker || a.name}`}
                            checked={selected.has(a.asset_id)}
                            onChange={(e) => setSelected((p) => {
                              const next = new Set(p)
                              if (e.target.checked) next.add(a.asset_id)
                              else next.delete(a.asset_id)
                              return next
                            })}
                          />
                        </td>
                        <td className="py-1.5">
                          <a className="font-medium text-gray-900 dark:text-white hover:underline" href={`/assets/${a.asset_id}`}>
                            {a.ticker || a.name}
                          </a>
                          {a.ticker && <span className="ml-1 text-[11px] text-gray-500">{a.name}</span>}
                        </td>
                        <td className="py-1.5 text-gray-600 dark:text-gray-400">{a.asset_class} · {a.country}</td>
                        <td className="py-1.5 text-right tnum money">{fmtBRL(Number(a.value_brl))}</td>
                        <td className="py-1.5 pl-4">
                          <select
                            aria-label={`letra ${a.ticker || a.name}`}
                            className={select}
                            disabled={saving}
                            value={a.source === 'manual' ? (a.category ?? '') : ''}
                            onChange={(e) => onCategory(a, e.target.value)}
                          >
                            <option value="">
                              Automático{a.derived_category ? ` (${ARCA_LETTER_LABEL[a.derived_category]})` : ' (nenhuma)'}
                            </option>
                            {CATEGORY_OPTIONS.map((c) => <option key={c} value={c}>{ARCA_LETTER_LABEL[c]}</option>)}
                          </select>
                        </td>
                        <td className="py-1.5">
                          {subs.length > 0 ? (
                            <select
                              aria-label={`sub ${a.ticker || a.name}`}
                              className={select}
                              disabled={saving}
                              value={a.subcategory ?? ''}
                              onChange={(e) => onSub(a, e.target.value)}
                            >
                              <option value="">—</option>
                              {subs.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
                            </select>
                          ) : (
                            <span className="text-gray-400">{a.subcategory ? ARCA_SUB_LABEL[a.subcategory] : '—'}</span>
                          )}
                        </td>
                        <td className="py-1.5">
                          <span className={`px-1.5 py-0.5 rounded text-[10px] ${badge.cls}`}>{badge.label}</span>
                          {a.source === 'derived' && a.derived_note && (
                            <span className="ml-1.5 text-[10px] text-gray-500" data-testid={`arca-note-${a.asset_id}`}>
                              {a.derived_note}
                            </span>
                          )}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>
    </AppLayout>
  )
}
