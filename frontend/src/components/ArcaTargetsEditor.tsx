/* Spec 85 — aba "ARCA" da página de Alocação alvo: meta + banda por letra e
 * metas de subcategoria (em % da letra). Salva as dimensões ARCA e ARCA_SUB.
 * O estado nasce de `data`; o pai remonta (via `key`) quando `data` muda. */
import { useMemo, useState } from 'react'

import { api, type ArcaLetter, type TargetAllocationOut, type TargetEntryIn } from '../lib/api'
import {
  ARCA_LETTER_COLOR,
  ARCA_LETTER_LABEL,
  ARCA_LETTERS,
  ARCA_PRESET,
  ARCA_SUBS,
  arcaParent,
} from '../lib/arca'
import { useEscapeKey } from '../lib/useEscapeKey'

type LetterDraft = { target: string; min: string; max: string }

function toPct(v: string | null | undefined, fallback = ''): string {
  if (v == null) return fallback
  return (Number(v) * 100).toFixed(2).replace(/\.?0+$/, '') || '0'
}

function toDec(v: string): string {
  return (Number(v.replace(',', '.')) / 100).toFixed(4)
}

function num(v: string): number {
  return Number((v || '').replace(',', '.')) || 0
}

function draftFrom(data: TargetAllocationOut | null) {
  const letters = Object.fromEntries(
    ARCA_LETTERS.map((l) => [l, { target: '', min: '10', max: '40' }]),
  ) as Record<ArcaLetter, LetterDraft>
  const subs: Record<string, string> = {}
  for (const e of data?.ARCA.entries ?? []) {
    letters[e.key as ArcaLetter] = {
      target: toPct(e.target_pct),
      min: toPct(e.min_pct, '10'),
      max: toPct(e.max_pct, '40'),
    }
  }
  for (const e of data?.ARCA_SUB.entries ?? []) subs[e.key] = toPct(e.target_pct)
  return { letters, subs }
}

export default function ArcaTargetsEditor({
  workspaceId,
  data,
  onSaved,
}: {
  workspaceId: string
  data: TargetAllocationOut | null
  onSaved: (d: TargetAllocationOut) => void
}) {
  const initial = useMemo(() => draftFrom(data), [data])
  const [letters, setLetters] = useState(initial.letters)
  const [subs, setSubs] = useState(initial.subs)
  const [dirty, setDirty] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [confirmOpen, setConfirmOpen] = useState(false)

  useEscapeKey(() => { if (confirmOpen) setConfirmOpen(false) })

  const letterSum = ARCA_LETTERS.reduce((a, l) => a + num(letters[l].target), 0)
  const subSums = Object.fromEntries(
    ARCA_LETTERS.map((l) => [
      l,
      ARCA_SUBS[l].reduce((a, s) => a + (subs[s.key] ? num(subs[s.key]) : 0), 0),
    ]),
  ) as Record<ArcaLetter, number>
  const subUsed = (l: ArcaLetter) => ARCA_SUBS[l].some((s) => (subs[s.key] ?? '') !== '')
  const problems: string[] = []
  if (Math.abs(letterSum - 100) > 0.01) problems.push(`As letras somam ${letterSum.toFixed(2)}%, precisam somar 100%.`)
  for (const l of ARCA_LETTERS) {
    const d = letters[l]
    if (d.target !== '' && (num(d.target) < num(d.min) || num(d.target) > num(d.max))) {
      problems.push(`${ARCA_LETTER_LABEL[l]}: meta fora da banda ${d.min}–${d.max}%.`)
    }
    if (subUsed(l) && Math.abs(subSums[l] - 100) > 0.01) {
      problems.push(`${ARCA_LETTER_LABEL[l]}: subcategorias somam ${subSums[l].toFixed(2)}% da letra.`)
    }
  }

  function setLetter(l: ArcaLetter, field: keyof LetterDraft, v: string) {
    setLetters((p) => ({ ...p, [l]: { ...p[l], [field]: v } }))
    setDirty(true)
  }

  function restorePreset() {
    setLetters({ ...ARCA_PRESET.letters })
    setSubs({ ...ARCA_PRESET.subs })
    setDirty(true)
  }

  async function save() {
    setConfirmOpen(false)
    setSaving(true)
    setError('')
    try {
      const letterEntries: TargetEntryIn[] = ARCA_LETTERS
        .filter((l) => letters[l].target !== '')
        .map((l) => ({
          key: l,
          target_pct: toDec(letters[l].target),
          min_pct: toDec(letters[l].min || '0'),
          max_pct: toDec(letters[l].max || '100'),
        }))
      await api.putTargetAllocation(workspaceId, 'ARCA', letterEntries)
      const subEntries: TargetEntryIn[] = Object.entries(subs)
        .filter(([k, v]) => v !== '' && arcaParent(k))
        .map(([k, v]) => ({ key: k, target_pct: toDec(v) }))
      const out = await api.putTargetAllocation(workspaceId, 'ARCA_SUB', subEntries)
      setDirty(false)
      onSaved(out)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Erro ao salvar.')
    } finally {
      setSaving(false)
    }
  }

  const input = 'h-8 w-20 rounded-md border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-900 px-2 text-right text-[13px] tnum'

  return (
    <div className="p-5 space-y-4" data-testid="arca-editor">
      <p className="text-[12px] text-gray-500 dark:text-gray-400">
        Meta por letra com banda de tolerância (o método usa 25% em cada uma, entre
        10% e 40%). As subcategorias são em <strong>% da letra</strong>; deixe em branco
        para não ter meta interna. Revise quando quiser — as metas ficam salvas e
        editáveis.
      </p>
      {error && (
        <div className="rounded-lg border border-red-200 dark:border-red-900 bg-red-50 dark:bg-red-900/20 p-3 text-[13px] text-red-700 dark:text-red-300">
          {error}
        </div>
      )}

      <div className="space-y-3">
        {ARCA_LETTERS.map((l) => (
          <div key={l} className="rounded-lg border border-gray-200 dark:border-gray-800 p-3">
            <div className="flex flex-wrap items-center gap-3">
              <span className="inline-block w-2.5 h-2.5 rounded-full" style={{ background: ARCA_LETTER_COLOR[l] }} />
              <span className="font-medium text-[13px] text-gray-900 dark:text-white w-44">{ARCA_LETTER_LABEL[l]}</span>
              <label className="text-[11px] text-gray-500 flex items-center gap-1">
                Meta %
                <input
                  aria-label={`meta ${l}`}
                  className={input}
                  value={letters[l].target}
                  onChange={(e) => setLetter(l, 'target', e.target.value)}
                />
              </label>
              <label className="text-[11px] text-gray-500 flex items-center gap-1">
                mín
                <input aria-label={`min ${l}`} className={input} value={letters[l].min}
                  onChange={(e) => setLetter(l, 'min', e.target.value)} />
              </label>
              <label className="text-[11px] text-gray-500 flex items-center gap-1">
                máx
                <input aria-label={`max ${l}`} className={input} value={letters[l].max}
                  onChange={(e) => setLetter(l, 'max', e.target.value)} />
              </label>
            </div>
            <div className="mt-2 grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-1 pl-5">
              {ARCA_SUBS[l].map((s) => (
                <label key={s.key} className="flex items-center justify-between gap-2 text-[12px] text-gray-700 dark:text-gray-300">
                  <span title={s.hint}>
                    {s.label} <span className="text-[10px] text-gray-400">{s.hint}</span>
                  </span>
                  <input
                    aria-label={`sub ${s.key}`}
                    className={input}
                    placeholder="—"
                    value={subs[s.key] ?? ''}
                    onChange={(e) => { setSubs((p) => ({ ...p, [s.key]: e.target.value })); setDirty(true) }}
                  />
                </label>
              ))}
            </div>
            {subUsed(l) && (
              <div className={`mt-1 pl-5 text-[11px] ${Math.abs(subSums[l] - 100) > 0.01 ? 'text-red-600' : 'text-emerald-600'}`}>
                Subcategorias: {subSums[l].toFixed(2)}% da letra
              </div>
            )}
          </div>
        ))}
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <span
          data-testid="arca-sum"
          className={`px-2 py-1 rounded text-[12px] font-medium ${Math.abs(letterSum - 100) > 0.01 ? 'bg-red-50 text-red-700 dark:bg-red-900/30 dark:text-red-300' : 'bg-emerald-50 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300'}`}
        >
          Total: {letterSum.toFixed(2)}%
        </span>
        <div className="flex gap-2">
          <button
            type="button"
            data-testid="arca-preset"
            onClick={restorePreset}
            className="h-8 px-3 text-[12px] rounded-md border border-gray-300 dark:border-gray-700"
          >
            Usar ponto de partida ARCA
          </button>
          <button
            type="button"
            data-testid="arca-save"
            disabled={!dirty || problems.length > 0 || saving}
            onClick={() => setConfirmOpen(true)}
            className="h-8 px-3 text-[12px] font-medium rounded-md bg-indigo-500 hover:bg-indigo-400 text-white disabled:opacity-50"
          >
            {saving ? 'Salvando…' : 'Salvar metas ARCA'}
          </button>
        </div>
      </div>
      {problems.length > 0 && dirty && (
        <ul className="text-[11px] text-red-600 space-y-0.5" data-testid="arca-problems">
          {problems.map((p) => <li key={p}>{p}</li>)}
        </ul>
      )}

      {confirmOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={() => setConfirmOpen(false)}>
          <div
            role="dialog"
            className="w-full max-w-sm rounded-xl bg-white dark:bg-gray-900 p-5 shadow-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <p className="text-sm text-gray-800 dark:text-gray-200">
              Substituir as metas ARCA atuais (letras e subcategorias)?
            </p>
            <div className="mt-4 flex justify-end gap-2">
              <button className="h-8 px-3 text-[12px] rounded-md border border-gray-300 dark:border-gray-700" onClick={() => setConfirmOpen(false)}>
                Cancelar
              </button>
              <button data-testid="arca-confirm" className="h-8 px-3 text-[12px] font-medium rounded-md bg-indigo-500 text-white" onClick={save}>
                Salvar
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
