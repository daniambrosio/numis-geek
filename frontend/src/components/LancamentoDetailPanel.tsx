import { useEffect, useState } from 'react'
import { CheckCircle2, AlertTriangle, Clock, XCircle, RefreshCw, X } from 'lucide-react'
import {
  api,
  type AssetOut, type AttachmentOut, type FinancialInstitutionOut,
  type AssetMovementOut, type AssetMovementRequest,
  type NotionSyncStatus, type SyncOut,
} from '../lib/api'
import { KLASS, collapsedOf, lanTypeColor } from '../lib/tokens'
import { CcyPill, ClassBadge, FILogo, TypeBadge } from './ui'
import NotesAttachmentsCard from './NotesAttachmentsCard'

interface Props {
  lancamento: AssetMovementOut
  asset: AssetOut | null
  fi: FinancialInstitutionOut | null
  onClose: () => void
  onEdit: () => void
  onDeactivate: () => void
  onSyncUpdated?: (out: SyncOut) => void
  /** Spec 51 — segunda chance: roda o preview de impacto em fechamentos
   *  pra este lançamento e abre o AffectedSnapshotsModal se houver. */
  onCheckImpact?: () => void
  /** Optional: caller can supply an "Updated" hook so the parent list
   *  shows fresh notes / attachments after edits made inside the panel. */
  onUpdated?: (m: AssetMovementOut) => void
}

function fmtMoney(n: number | null | undefined, currency: string, opts: { sign?: boolean } = {}) {
  if (n == null) return '—'
  const v = opts.sign ? Math.abs(n) : n
  const sign = opts.sign && n > 0 ? '+ ' : opts.sign && n < 0 ? '− ' : ''
  return sign + v.toLocaleString('pt-BR', { style: 'currency', currency })
}

function fmtNum(n: number | null | undefined, digits = 8) {
  if (n == null) return '—'
  return n.toLocaleString('pt-BR', { maximumFractionDigits: digits })
}

export default function LancamentoDetailPanel({
  lancamento: l, asset, fi, onClose, onEdit, onDeactivate, onSyncUpdated, onCheckImpact, onUpdated,
}: Props) {
  const [attachments, setAttachments] = useState<AttachmentOut[]>([])
  const [notes, setNotes] = useState<string>(l.notes ?? '')

  // Resync local state when the parent swaps to a different lançamento.
  useEffect(() => { setNotes(l.notes ?? '') }, [l.id, l.notes])

  // Load persisted attachments for this lançamento.
  useEffect(() => {
    let cancelled = false
    api.listAttachments('movement', l.id)
      .then(list => { if (!cancelled) setAttachments(list) })
      .catch(() => { if (!cancelled) setAttachments([]) })
    return () => { cancelled = true }
  }, [l.id])

  useEffect(() => {
    function onEsc(e: KeyboardEvent) { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onEsc)
    return () => document.removeEventListener('keydown', onEsc)
  }, [onClose])

  async function refreshAttachments() {
    try {
      const list = await api.listAttachments('movement', l.id)
      setAttachments(list)
    } catch { /* fail-soft */ }
  }

  async function saveNotes(next: string): Promise<void> {
    // PUT requires the full payload — reconstruct from the current entity.
    const payload: AssetMovementRequest = {
      asset_id: l.asset_id,
      type: l.type,
      event_date: l.event_date,
      settlement_date: l.settlement_date,
      quantity: l.quantity,
      unit_price: l.unit_price,
      gross_amount: l.gross_amount,
      fee: l.fee,
      tax: l.tax,
      net_amount: l.net_amount,
      currency: l.currency,
      fx_rate: l.fx_rate,
      notes: next.trim() ? next : null,
      nota_negociacao_number: l.nota_negociacao_number,
      external_id: l.external_id,
      external_source: l.external_source,
    }
    const updated = await api.updateAssetMovement(l.id, payload)
    setNotes(updated.notes ?? '')
    onUpdated?.(updated)
  }

  const typeColor = lanTypeColor(l.type)
  const klass = asset ? collapsedOf(asset.asset_class) : null

  return (
    <div className="fixed inset-0 z-50">
      <div className="absolute inset-0 bg-black/50 backdrop-blur-[2px]" onClick={onClose} />
      <aside className="absolute right-0 top-0 h-full w-full sm:w-[520px] bg-gray-50 dark:bg-gray-950 border-l border-gray-200 dark:border-gray-800 shadow-2xl overflow-y-auto scrollbar-thin flex flex-col">
        {/* Sticky header */}
        <div className="sticky top-0 z-10 bg-gray-50 dark:bg-gray-950 border-b border-gray-200 dark:border-gray-800 px-5 py-3.5 flex items-center justify-between gap-3">
          <div className="min-w-0 flex-1 flex items-center gap-2">
            <span className="w-1.5 h-8 rounded-full shrink-0" style={{ background: typeColor }} />
            <div className="min-w-0">
              <div className="text-[10px] uppercase tracking-wider text-gray-500 flex items-center gap-1.5">
                <TypeBadge code={l.type} label={l.type_label} />
                <CcyPill ccy={l.currency} />
              </div>
              <div className="text-sm font-semibold truncate text-gray-900 dark:text-white">
                {asset?.ticker ? <span className="font-mono">{asset.ticker} </span> : null}
                {asset?.name ?? '—'}
              </div>
            </div>
          </div>
          <button
            onClick={onClose}
            title="Fechar (Esc)"
            className="w-8 h-8 inline-flex items-center justify-center rounded-md text-gray-500 hover:text-gray-700 dark:hover:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-800 transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="p-5 space-y-5 flex-1">
          {/* Asset summary block */}
          {asset && (
            <div className="rounded-xl bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 p-3 flex items-center gap-3">
              <span className="w-1 h-10 rounded-full shrink-0" style={{ background: klass ? KLASS[klass].color : '#94a3b8' }} />
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  {asset.ticker && <span className="font-mono text-[12px] font-medium text-gray-900 dark:text-white">{asset.ticker}</span>}
                  {klass && <ClassBadge klass={klass} size="xs" withDot={false} />}
                </div>
                <div className="text-[11px] text-gray-500 dark:text-gray-400 truncate">{asset.name}</div>
              </div>
              {fi && (
                <div className="flex items-center gap-1.5 shrink-0">
                  <FILogo slug={fi.logo_slug} shortName={fi.short_name} size="sm" />
                  <span className="text-[11px] text-gray-500 dark:text-gray-400">{fi.short_name}</span>
                </div>
              )}
            </div>
          )}

          {/* Fields grid */}
          <dl className="grid grid-cols-2 gap-3 text-[12px]">
            <Field label="Data" value={l.event_date} mono />
            <Field label="Liquidação" value={l.settlement_date ?? '—'} mono />
            <Field label="Quantidade" value={fmtNum(l.quantity)} tnum />
            <Field label="Preço unit." value={fmtMoney(l.unit_price, l.currency)} money tnum />
            <Field label="Bruto" value={fmtMoney(l.gross_amount, l.currency)} money tnum />
            <Field label="Taxa" value={fmtMoney(l.fee, l.currency)} money tnum />
            <Field label="Imposto" value={fmtMoney(l.tax, l.currency)} money tnum />
            <Field
              label="Líquido"
              value={fmtMoney(l.net_amount, l.currency, { sign: true })}
              money tnum
              tone={l.net_amount > 0 ? 'positive' : l.net_amount < 0 ? 'negative' : undefined}
            />
            <Field label="Moeda" value={l.currency} />
            <Field
              label="FX rate"
              value={l.currency === 'USD' ? `R$ ${Number(l.fx_rate).toFixed(4)}` : '—'}
              tnum
            />
            <Field label="Nota negociação" value={l.nota_negociacao_number ?? '—'} mono />
            <Field label="Origem" value={l.external_source ?? 'manual'} />
          </dl>

          {/* Notion sync */}
          <NotionSyncSection l={l} onUpdated={onSyncUpdated} />

          {/* Notes & attachments — mirrors prototype NotesAttachments (index.html:4168) */}
          <NotesAttachmentsCard
            notes={notes}
            onNotesSave={saveNotes}
            sourceType="movement"
            sourceId={l.id}
            attachments={attachments}
            onAttachmentsChanged={refreshAttachments}
          />
        </div>

        {/* Footer */}
        <div className="px-5 py-3 border-t border-gray-200 dark:border-gray-800 flex items-center justify-between gap-2">
          {onCheckImpact ? (
            <button
              onClick={onCheckImpact}
              title="Spec 51 — verifica fechamentos passados que estariam desincronizados com esse lançamento"
              className="h-8 px-3 inline-flex items-center rounded-lg text-[12px] text-amber-700 dark:text-amber-400 hover:bg-amber-50 dark:hover:bg-amber-900/20 transition-colors"
              data-testid="lancamento-check-impact"
            >
              Verificar impacto em fechamentos
            </button>
          ) : <span />}
          <div className="flex items-center gap-2">
            {l.is_active && (
              <button
                onClick={onDeactivate}
                className="h-8 px-3 inline-flex items-center rounded-lg text-[12px] border border-red-200 dark:border-red-900 text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors"
              >
                Desativar
              </button>
            )}
            <button
              onClick={onEdit}
              className="h-8 px-3 inline-flex items-center rounded-lg text-[12px] bg-indigo-500 hover:bg-indigo-400 text-white font-medium transition-colors"
            >
              Editar
            </button>
          </div>
        </div>
      </aside>
    </div>
  )
}

function NotionSyncSection({
  l, onUpdated,
}: { l: AssetMovementOut; onUpdated?: (out: SyncOut) => void }) {
  const [status, setStatus] = useState<NotionSyncStatus>(l.notion_sync_status)
  const [error, setError] = useState<string | null>(l.notion_sync_error)
  const [lastSyncedAt, setLastSyncedAt] = useState<string | null>(l.notion_last_synced_at)
  const [busy, setBusy] = useState(false)
  const [conflictAt, setConflictAt] = useState<string | null>(null)

  async function push(force = false) {
    setBusy(true)
    try {
      const out = await api.notionPushMovement(l.id, force)
      setStatus(out.status)
      setError(out.error)
      if (out.status === 'SYNCED') {
        setLastSyncedAt(new Date().toISOString())
        setConflictAt(null)
      } else if (out.status === 'CONFLICT') {
        setConflictAt(out.conflict_remote_edited_at ?? null)
      }
      onUpdated?.(out)
    } catch (e) {
      setStatus('ERROR')
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  async function abort() {
    try {
      await api.notionResolve('asset-movement', l.id, 'abort')
      setStatus('PENDING')
      setError(null)
      setConflictAt(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  const pill = NOTION_PILL[status]

  return (
    <div className="rounded-xl bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 p-3 space-y-2">
      <div className="flex items-center justify-between gap-2">
        <div className="text-[10px] font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider">
          Sync Notion
        </div>
        <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] font-medium ${pill.cls}`}>
          <pill.Icon className="w-3 h-3" /> {pill.label}
        </span>
      </div>
      {lastSyncedAt && status === 'SYNCED' && (
        <div className="text-[11px] text-gray-500 dark:text-gray-400">
          Última sincronização: {new Date(lastSyncedAt).toLocaleString('pt-BR')}
        </div>
      )}
      {error && status !== 'SYNCED' && (
        <div className="text-[11px] text-red-600 dark:text-red-400">{error}</div>
      )}
      <div className="flex items-center justify-end gap-2 pt-1">
        <button
          onClick={() => push(false)}
          disabled={busy}
          className="h-7 px-2.5 inline-flex items-center gap-1 rounded-md text-[11px] bg-indigo-500 hover:bg-indigo-400 text-white disabled:opacity-50"
        >
          <RefreshCw className={`w-3 h-3 ${busy ? 'animate-spin' : ''}`} />
          {status === 'SYNCED' ? 'Re-sincronizar' : 'Sincronizar'}
        </button>
      </div>
      {status === 'CONFLICT' && (
        <ConflictModal
          remoteEditedAt={conflictAt}
          onForce={() => push(true)}
          onAbort={abort}
          busy={busy}
        />
      )}
    </div>
  )
}

const NOTION_PILL: Record<NotionSyncStatus, { label: string; cls: string; Icon: typeof CheckCircle2 }> = {
  PENDING: {
    label: 'Pendente',
    cls: 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300',
    Icon: Clock,
  },
  SYNCED: {
    label: 'Sincronizado',
    cls: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300',
    Icon: CheckCircle2,
  },
  CONFLICT: {
    label: 'Conflito',
    cls: 'bg-orange-100 text-orange-700 dark:bg-orange-900/40 dark:text-orange-300',
    Icon: AlertTriangle,
  },
  ERROR: {
    label: 'Erro',
    cls: 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300',
    Icon: XCircle,
  },
}

function ConflictModal({
  remoteEditedAt, onForce, onAbort, busy,
}: { remoteEditedAt: string | null; onForce: () => void; onAbort: () => void; busy: boolean }) {
  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/50">
      <div className="w-full max-w-md bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-700 shadow-xl p-6 space-y-4">
        <div className="flex items-center gap-2">
          <AlertTriangle className="w-5 h-5 text-orange-500" />
          <h2 className="text-base font-semibold text-gray-900 dark:text-white">
            Conflito com Notion
          </h2>
        </div>
        <p className="text-sm text-gray-600 dark:text-gray-300">
          A page no Notion foi editada
          {remoteEditedAt ? ` em ${new Date(remoteEditedAt).toLocaleString('pt-BR')}` : ''}
          {' '}depois da última sincronização. Forçar o push vai sobrescrever as
          mudanças que você fez no Notion.
        </p>
        <div className="flex justify-end gap-2">
          <button
            onClick={onAbort}
            disabled={busy}
            className="px-3 py-1.5 rounded-lg text-sm text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800 disabled:opacity-50"
          >
            Cancelar
          </button>
          <button
            onClick={onForce}
            disabled={busy}
            className="px-3 py-1.5 rounded-lg text-sm bg-red-600 hover:bg-red-500 text-white font-medium disabled:opacity-50"
          >
            Forçar push
          </button>
        </div>
      </div>
    </div>
  )
}

function Field({
  label, value, mono, money, tnum, tone,
}: {
  label: string
  value: string
  mono?: boolean
  money?: boolean
  tnum?: boolean
  tone?: 'positive' | 'negative'
}) {
  const toneCls =
    value === '—' ? 'text-gray-400 dark:text-gray-600'
    : tone === 'positive' ? 'text-emerald-500 dark:text-emerald-400'
    : tone === 'negative' ? 'text-red-500 dark:text-red-400'
    : 'text-gray-900 dark:text-white'
  const fontCls = mono ? 'font-mono' : ''
  const tnumCls = tnum ? 'tnum' : ''
  return (
    <div>
      <dt className="text-[10px] uppercase tracking-wider text-gray-500 dark:text-gray-400">{label}</dt>
      <dd className={`text-[12px] font-medium ${toneCls} ${fontCls} ${tnumCls}`}>
        {money ? <span className="money">{value}</span> : value}
      </dd>
    </div>
  )
}
