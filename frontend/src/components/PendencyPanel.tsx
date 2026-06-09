/* Spec 35 + 47 — Pendency review panel (canonical).
 *
 * Shown on /snapshots/{ym} when status === IN_REVIEW. Pendencies are
 * grouped by financial institution (sem instituição last) — that's how
 * the user normally goes through the closing (one statement per FI).
 *
 * Spec 47 made this the single source of truth — SnapshotDetail imports
 * it instead of duplicating the render. */
import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  AlertTriangle, ChevronDown, Edit2, Loader2, Lock, RefreshCw, RotateCcw,
  Upload,
} from 'lucide-react'

import {
  api,
  type AssetOut,
  type FinancialInstitutionOut,
  type SnapshotPendencyOut,
} from '../lib/api'
import { Card, ClassBadge } from './ui'
import { parseDecimal } from '../lib/parseDecimal'
import { collapsedOf } from '../lib/tokens'
import BulkAttachmentManager from './BulkAttachmentManager'
import ExtractionUploadModal from './ExtractionUploadModal'

const MONTH_NAMES_SHORT = [
  'Jan', 'Fev', 'Mar', 'Abr', 'Mai', 'Jun',
  'Jul', 'Ago', 'Set', 'Out', 'Nov', 'Dez',
]

function ymLabelShort(ym: string): string {
  // "2026-04" → "Abr/26"
  const [y, m] = ym.split('-')
  return `${MONTH_NAMES_SHORT[parseInt(m, 10) - 1]}/${y.slice(2)}`
}

function fmtBRL(n: number): string {
  return n.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })
}

function fmtDateBR(iso: string): string {
  const [y, m, d] = iso.slice(0, 10).split('-')
  return `${d}/${m}/${y}`
}

const UNGROUPED_FI_LABEL = 'Sem instituição'

interface FIGroup {
  name: string
  openItems: SnapshotPendencyOut[]
  resolvedCount: number
}

function groupPendenciesByFI(pendencies: SnapshotPendencyOut[]): FIGroup[] {
  const map = new Map<string, SnapshotPendencyOut[]>()
  for (const p of pendencies) {
    const k = p.asset_institution_short_name ?? UNGROUPED_FI_LABEL
    if (!map.has(k)) map.set(k, [])
    map.get(k)!.push(p)
  }
  // Sort: groups with open pendencies first; UNGROUPED last; alpha within.
  const groups = Array.from(map.entries())
    .map(([name, items]) => {
      const openItems = items
        .filter(p => !p.resolved_at)
        .sort((a, b) =>
          (a.asset_ticker ?? a.asset_name).localeCompare(
            b.asset_ticker ?? b.asset_name,
          ),
        )
      return {
        name,
        openItems,
        resolvedCount: items.length - openItems.length,
      }
    })
    .sort((a, b) => {
      if (a.name === UNGROUPED_FI_LABEL && b.name !== UNGROUPED_FI_LABEL) return 1
      if (b.name === UNGROUPED_FI_LABEL && a.name !== UNGROUPED_FI_LABEL) return -1
      const aHasOpen = a.openItems.length > 0
      const bHasOpen = b.openItems.length > 0
      if (aHasOpen !== bHasOpen) return aHasOpen ? -1 : 1
      return a.name.localeCompare(b.name)
    })
  return groups
}

interface Props {
  snapshotId: string
  pendencies: SnapshotPendencyOut[]
  assetById: Map<string, AssetOut>
  pendingTotal: number
  totalAssetsCount: number
  resolvedAssets: number
  periodEndDate: string
  onResolved: () => void
  onConfirm?: () => void
  confirming?: boolean
  /** Caller abre o SnapshotItemEditModal pra essa pendência (mesmo modal
   *  do clique na Posições Congeladas). Default: prompt nativo (legacy). */
  onEditPendency?: (pendency: SnapshotPendencyOut) => void
}

export default function PendencyPanel({
  snapshotId,
  pendencies, assetById,
  pendingTotal, totalAssetsCount, resolvedAssets,
  periodEndDate,
  onResolved, onConfirm, confirming, onEditPendency,
}: Props) {
  const groups = useMemo(
    () => groupPendenciesByFI(pendencies),
    [pendencies],
  )
  const pct = totalAssetsCount > 0
    ? Math.round((resolvedAssets / totalAssetsCount) * 100)
    : 0

  // Per-group expand state. `undefined` → use default (expanded if has open
  // pendencies, collapsed if fully resolved). Set to true/false when the
  // user toggles. This way grupos com FI já resolvido aparecem colapsados
  // mas continuam acessíveis pra subir mais arquivos (ex.: proventos).
  const [userToggled, setUserToggled] = useState<Map<string, boolean>>(new Map())
  function isExpanded(g: FIGroup): boolean {
    const u = userToggled.get(g.name)
    if (u !== undefined) return u
    return g.openItems.length > 0
  }
  function toggleGroup(name: string, next: boolean) {
    const m = new Map(userToggled)
    m.set(name, next)
    setUserToggled(m)
  }

  // Spec 58 — load FIs to map group name → id so each per-FI group can
  // pass institutionId to its own BulkAttachmentManager.
  const [fis, setFis] = useState<FinancialInstitutionOut[]>([])
  useEffect(() => {
    api.listFinancialInstitutions().then(setFis).catch(() => { /* silent */ })
  }, [])
  const fiIdByShortName = useMemo(() => {
    const m = new Map<string, string>()
    for (const f of fis) m.set(f.short_name, f.id)
    return m
  }, [fis])

  return (
    <Card padding="p-5" className="border-amber-500/30 bg-amber-500/[0.04]">
      <div className="flex items-center justify-between mb-4 gap-3 flex-wrap">
        <div>
          <div className="flex items-center gap-2">
            <AlertTriangle className="w-4 h-4 text-amber-500 dark:text-amber-400" />
            <h3 className="text-sm font-semibold">
              Resolver pendências antes de fechar
            </h3>
          </div>
          <div className="text-[11px] text-gray-500 mt-0.5">
            {pendingTotal} de {totalAssetsCount} ativos sem preço atualizado para{' '}
            {fmtDateBR(periodEndDate)}. Resolva todos e clique em{' '}
            <strong className="text-amber-700 dark:text-amber-300">
              Confirmar fechamento
            </strong>.
          </div>
        </div>
        {onConfirm && (
          <button
            onClick={onConfirm}
            disabled={pendingTotal > 0 || !!confirming}
            title={
              confirming
                ? 'Fechando…'
                : pendingTotal > 0
                  ? `Faltam ${pendingTotal} ativos`
                  : 'Tudo pronto'
            }
            className={`h-9 px-4 inline-flex items-center gap-1.5 rounded-lg text-[13px] font-medium transition-colors ${
              pendingTotal > 0
                ? 'bg-gray-100 dark:bg-gray-800 text-gray-400 cursor-not-allowed'
                : confirming
                  ? 'bg-emerald-500/70 text-white cursor-wait'
                  : 'bg-emerald-500 text-white hover:bg-emerald-400'
            }`}
          >
            {confirming
              ? <Loader2 className="w-3.5 h-3.5 animate-spin" />
              : <Lock className="w-3.5 h-3.5" />}
            {confirming ? 'Fechando…' : 'Confirmar fechamento'}
          </button>
        )}
      </div>

      {/* Progress */}
      <div className="mb-4">
        <div className="flex items-center justify-between text-[11px] mb-1.5">
          <span className="text-gray-500">
            {resolvedAssets} de {totalAssetsCount} resolvidos
          </span>
          <span className="text-gray-500 tnum">{pct}%</span>
        </div>
        <div className="h-2 w-full rounded-full bg-gray-200 dark:bg-gray-800 overflow-hidden">
          <div
            className="h-full bg-emerald-500 transition-all"
            style={{ width: `${pct}%` }}
          />
        </div>
      </div>

      {/* Spec 58 — per-FI groups, each with its own attachment manager.
          Upload inside a group scopes the extraction job to that FI.
          Grupos sem pendência aberta ainda aparecem (colapsados) pra
          permitir upload de arquivos adicionais (ex.: proventos). */}
      <div className="space-y-5">
        {groups.map(g => {
          const fiId = fiIdByShortName.get(g.name) ?? null
          const expanded = isExpanded(g)
          const hasOpen = g.openItems.length > 0
          return (
            <div key={g.name} data-testid={`pendency-group-${g.name}`}>
              <button
                type="button"
                onClick={() => toggleGroup(g.name, !expanded)}
                className="w-full flex items-center justify-between mb-1.5 text-left hover:opacity-80 transition-opacity"
                data-testid={`pendency-group-toggle-${g.name}`}
              >
                <div className="flex items-center gap-1.5">
                  <ChevronDown
                    className={`w-3.5 h-3.5 text-gray-500 transition-transform ${
                      expanded ? '' : '-rotate-90'
                    }`}
                  />
                  <div className="text-[11px] font-semibold uppercase tracking-wider text-gray-700 dark:text-gray-300">
                    {g.name}
                  </div>
                </div>
                <div className="text-[10px] text-gray-500 tnum">
                  {hasOpen
                    ? `${g.openItems.length} aberta${g.openItems.length === 1 ? '' : 's'}`
                    : `${g.resolvedCount} resolvida${g.resolvedCount === 1 ? '' : 's'}`}
                </div>
              </button>
              {expanded && (
                <>
                  <div
                    className={`grid gap-3 ${fiId ? 'grid-cols-1 md:grid-cols-2' : 'grid-cols-1'}`}
                  >
                    <BulkAttachmentManager
                      snapshotId={snapshotId}
                      pendencies={pendencies}
                      onResolved={onResolved}
                      institutionId={fiId}
                      purpose="positions"
                    />
                    {fiId && (
                      <BulkAttachmentManager
                        snapshotId={snapshotId}
                        pendencies={pendencies}
                        onResolved={onResolved}
                        institutionId={fiId}
                        purpose="income"
                      />
                    )}
                  </div>
                  {hasOpen && (
                    <div className="space-y-2 mt-2">
                      {g.openItems.map(p => (
                        <PendencyRow
                          key={p.id}
                          pendency={p}
                          asset={assetById.get(p.asset_id)}
                          onResolved={onResolved}
                          onEditPendency={onEditPendency}
                        />
                      ))}
                    </div>
                  )}
                </>
              )}
            </div>
          )
        })}
      </div>

      <div className="mt-4 pt-3 border-t border-amber-500/20 text-[11px] text-gray-500">
        <strong className="text-gray-700 dark:text-gray-300">
          Como o sistema processa:
        </strong>{' '}
        upload de PDF/screenshot/CSV/XLSX dispara LLM agent (spec 38)
        pra extrair cotação, posição ou rendimento.
      </div>
    </Card>
  )
}

function PendencyRow({
  pendency, asset, onResolved, onEditPendency,
}: {
  pendency: SnapshotPendencyOut
  asset: AssetOut | undefined
  onResolved: () => void
  onEditPendency?: (pendency: SnapshotPendencyOut) => void
}) {
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [uploadOpen, setUploadOpen] = useState(false)
  const isManual =
    pendency.reason === 'MANUAL_SOURCE'
    || pendency.reason === 'UPLOAD_REQUIRED'
    || pendency.reason === 'HISTORICAL_PRICE_REQUIRED'
  const prevPriceNum =
    pendency.previous_unit_price != null
      ? Number(pendency.previous_unit_price)
      : null
  const hasPrevious =
    prevPriceNum != null
    && Number.isFinite(prevPriceNum)
    && pendency.previous_period_end != null

  async function handleRetry() {
    setBusy(true); setErr(null)
    try { await api.retrySnapshotPendencyApi(pendency.id); onResolved() }
    catch (e) { setErr(e instanceof Error ? e.message : 'Erro') }
    finally { setBusy(false) }
  }
  async function handleRepeatPrevious() {
    if (!hasPrevious) return
    setBusy(true); setErr(null)
    try {
      await api.resolveSnapshotPendency(pendency.id, {
        new_price: pendency.previous_unit_price!,
        note: `copied from ${pendency.previous_period_end}`,
      })
      onResolved()
    } catch (e) { setErr(e instanceof Error ? e.message : 'Erro') }
    finally { setBusy(false) }
  }
  function handleEdit() {
    // Preferido: SnapshotItemEditModal (mesmo modal das Posições Congeladas),
    // que suporta toggle preço unitário ↔ valor total, preview, notas e
    // remoção. patchSnapshotItem no backend marca a pendência como
    // resolved automaticamente. Fallback pra window.prompt mantido só pra
    // testes/legacy que não passam o callback.
    if (onEditPendency) { onEditPendency(pendency); return }
    const raw = window.prompt(
      `Novo preço para ${pendency.asset_ticker ?? pendency.asset_name}:`,
      hasPrevious ? prevPriceNum!.toFixed(2).replace('.', ',') : '',
    )
    if (!raw) return
    const n = parseDecimal(raw)
    if (n == null || n < 0) { setErr('Informe um número >= 0'); return }
    setBusy(true); setErr(null)
    api.resolveSnapshotPendency(pendency.id, { new_price: n.toFixed(2) })
      .then(() => onResolved())
      .catch(e => setErr(e instanceof Error ? e.message : 'Erro'))
      .finally(() => setBusy(false))
  }

  return (
    <div
      className="flex items-center gap-3 p-2.5 rounded-lg bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800"
      data-testid={`pendency-row-${pendency.id}`}
    >
      <span className={`w-1 h-8 rounded-full ${isManual ? 'bg-amber-500' : 'bg-red-500'}`} />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <Link
            to={`/assets/${pendency.asset_id}`}
            className="font-mono font-medium text-[13px] text-gray-900 dark:text-gray-100 hover:text-indigo-500"
          >
            {pendency.asset_ticker ?? pendency.asset_name}
          </Link>
          {asset && (
            <ClassBadge klass={collapsedOf(asset.asset_class)} size="xs" withDot={false} />
          )}
        </div>
        <div className="text-[11px] text-gray-500 truncate">
          {pendency.detail ?? pendency.asset_name}
          {hasPrevious && (
            <span className="ml-2 text-gray-600 dark:text-gray-300 tnum">
              · {ymLabelShort(pendency.previous_period_end!.slice(0, 7))}:{' '}
              {fmtBRL(prevPriceNum!)}
            </span>
          )}
        </div>
        {err && <div className="text-[10px] text-red-500 mt-0.5">{err}</div>}
      </div>
      <div className="flex items-center gap-1.5">
        {pendency.action_type === 'RETRY_API' && (
          <button
            onClick={handleRetry}
            disabled={busy}
            className="h-7 px-2.5 inline-flex items-center gap-1 rounded-md text-[11px] bg-indigo-500/15 text-indigo-600 dark:text-indigo-300 hover:bg-indigo-500/25 disabled:opacity-50"
          >
            <RefreshCw className={`w-3 h-3 ${busy ? 'animate-spin' : ''}`} /> Retry
          </button>
        )}
        {pendency.action_type === 'UPLOAD_FILE' && (
          <button
            onClick={() => setUploadOpen(true)}
            disabled={busy}
            className="h-7 px-2.5 inline-flex items-center gap-1 rounded-md text-[11px] bg-amber-500/15 text-amber-700 dark:text-amber-300 hover:bg-amber-500/25 disabled:opacity-50"
            data-testid={`pendency-upload-${pendency.id}`}
          >
            <Upload className="w-3 h-3" /> Upload extrato
          </button>
        )}
        {hasPrevious && (
          <button
            onClick={handleRepeatPrevious}
            disabled={busy}
            title={`Usar preço de ${ymLabelShort(pendency.previous_period_end!.slice(0, 7))}: ${fmtBRL(prevPriceNum!)}`}
            className="h-7 px-2.5 inline-flex items-center gap-1 rounded-md text-[11px] bg-indigo-500 text-white hover:bg-indigo-400 disabled:opacity-50"
            data-testid={`pendency-repeat-${pendency.id}`}
          >
            <RotateCcw className="w-3 h-3" /> Repetir
          </button>
        )}
        <button
          onClick={handleEdit}
          disabled={busy}
          className="h-7 px-2.5 inline-flex items-center gap-1 rounded-md text-[11px] bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700 disabled:opacity-50"
        >
          <Edit2 className="w-3 h-3" /> Editar
        </button>
      </div>

      {uploadOpen && (
        <ExtractionUploadModal
          pendency={pendency}
          onResolved={onResolved}
          onClose={() => setUploadOpen(false)}
        />
      )}
    </div>
  )
}
