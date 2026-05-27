import { useState } from 'react'
import { X, Upload, Sparkles } from 'lucide-react'

import {
  api,
  type ExtractionJobOut, type ExtractionSourceHint, type SnapshotPendencyOut,
} from '../lib/api'
import ConfidencePill from './ConfidencePill'

type Stage = 'pick' | 'uploading' | 'review' | 'applied'

interface Props {
  pendency: SnapshotPendencyOut
  onResolved: () => void
  onClose: () => void
}

const HINT_OPTIONS: { value: ExtractionSourceHint; label: string }[] = [
  { value: 'SCREENSHOT_PRICE', label: 'Screenshot de cotação' },
  { value: 'BROKER_POSITION',  label: 'Extrato de posição' },
  { value: 'BROKER_INCOME',    label: 'Extrato de proventos' },
  { value: 'B3_TRADE_NOTE',    label: 'Nota de corretagem B3' },
  { value: 'FGTS_BALANCE',     label: 'Saldo FGTS' },
  { value: 'GENERIC',          label: 'Detectar automaticamente' },
]

const ACCEPTED_MIME = 'image/png,image/jpeg,image/webp,application/pdf,text/csv'

export default function ExtractionUploadModal({ pendency, onResolved, onClose }: Props) {
  const [stage, setStage] = useState<Stage>('pick')
  const [file, setFile] = useState<File | null>(null)
  const [hint, setHint] = useState<ExtractionSourceHint>('SCREENSHOT_PRICE')
  const [job, setJob] = useState<ExtractionJobOut | null>(null)
  const [applyResult, setApplyResult] = useState<{ applied_count: number; skipped_count: number; errors: string[] } | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function handleExtract() {
    if (!file) return
    setStage('uploading')
    setError(null)
    try {
      const att = await api.uploadAttachment('asset', pendency.asset_id, file)
      const created = await api.createExtraction({
        attachment_id: att.id,
        source_hint: hint,
        pendency_id: pendency.id,
        snapshot_id: pendency.snapshot_id,
        asset_id: pendency.asset_id,
      })
      if (created.status === 'FAILED') {
        setError(created.error_message ?? 'Extração falhou.')
        setStage('pick')
        return
      }
      setJob(created)
      setStage('review')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Erro no upload')
      setStage('pick')
    }
  }

  async function handleConfirm() {
    if (!job) return
    setError(null)
    try {
      const result = await api.confirmExtraction(job.id)
      setApplyResult(result)
      setStage('applied')
      // Tiny delay so the user can read the toast before the panel re-renders.
      setTimeout(() => { onResolved(); onClose() }, 1500)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Erro ao aplicar')
    }
  }

  async function handleReject() {
    if (!job) return
    try {
      await api.rejectExtraction(job.id, 'descartado pelo usuário')
      onClose()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Erro')
    }
  }

  const target = pendency.asset_ticker ?? pendency.asset_name

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/60 p-4">
      <div className="w-full max-w-2xl bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-700 shadow-2xl flex flex-col max-h-[90vh]">
        <div className="px-5 py-3 border-b border-gray-200 dark:border-gray-800 flex items-center justify-between">
          <div>
            <div className="text-sm font-semibold text-gray-900 dark:text-white">
              Upload extrato — {target}
            </div>
            <div className="text-[11px] text-gray-500 dark:text-gray-400 flex items-center gap-1">
              <Sparkles className="w-3 h-3 text-indigo-500" />
              extração via LLM · revisão obrigatória
            </div>
          </div>
          <button
            onClick={onClose}
            className="w-7 h-7 inline-flex items-center justify-center rounded-md text-gray-400 hover:text-gray-700 dark:hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="p-5 overflow-y-auto flex-1 space-y-4">
          {stage === 'pick' && (
            <PickStage
              file={file} setFile={setFile}
              hint={hint} setHint={setHint}
              error={error}
            />
          )}
          {stage === 'uploading' && (
            <div className="flex flex-col items-center justify-center py-12 gap-3" data-testid="extraction-uploading">
              <div className="w-10 h-10 border-4 border-indigo-500/40 border-t-indigo-500 rounded-full animate-spin" />
              <div className="text-[12px] text-gray-600 dark:text-gray-300">
                Extraindo dados…
              </div>
              <div className="text-[10px] text-gray-400">isso pode levar 10-30 segundos</div>
            </div>
          )}
          {stage === 'review' && job && (
            <ReviewStage job={job} error={error} />
          )}
          {stage === 'applied' && applyResult && (
            <div className="rounded-lg bg-emerald-50 dark:bg-emerald-900/20 border border-emerald-200 dark:border-emerald-900 p-4" data-testid="extraction-applied">
              <div className="text-[12px] font-semibold text-emerald-700 dark:text-emerald-300">
                ✓ Aplicado · {applyResult.applied_count} {applyResult.applied_count === 1 ? 'registro' : 'registros'}
              </div>
              {applyResult.skipped_count > 0 && (
                <div className="text-[11px] text-emerald-600 dark:text-emerald-400 mt-1">
                  {applyResult.skipped_count} ignorado{applyResult.skipped_count === 1 ? '' : 's'}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-5 py-3 border-t border-gray-200 dark:border-gray-800 flex justify-end gap-2">
          {stage === 'pick' && (
            <>
              <button
                onClick={onClose}
                className="h-8 px-3 inline-flex items-center rounded-md text-[12px] text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800"
              >
                Cancelar
              </button>
              <button
                onClick={handleExtract}
                disabled={!file}
                className="h-8 px-3 inline-flex items-center gap-1.5 rounded-md bg-indigo-500 hover:bg-indigo-400 disabled:opacity-50 text-white text-[12px] font-medium"
              >
                <Upload className="w-3 h-3" /> Extrair
              </button>
            </>
          )}
          {stage === 'review' && (
            <>
              <button
                onClick={handleReject}
                className="h-8 px-3 inline-flex items-center rounded-md text-[12px] border border-red-200 dark:border-red-900 text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20"
              >
                Descartar
              </button>
              <button
                onClick={handleConfirm}
                className="h-8 px-3 inline-flex items-center rounded-md bg-emerald-500 hover:bg-emerald-400 text-white text-[12px] font-medium"
                data-testid="extraction-confirm"
              >
                ✓ Confirmar e aplicar
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  )
}


function PickStage({
  file, setFile, hint, setHint, error,
}: {
  file: File | null
  setFile: (f: File | null) => void
  hint: ExtractionSourceHint
  setHint: (h: ExtractionSourceHint) => void
  error: string | null
}) {
  return (
    <div className="space-y-4">
      <div>
        <label className="block text-[10px] uppercase tracking-wider font-semibold text-gray-500 dark:text-gray-400 mb-1.5">
          Tipo de documento
        </label>
        <select
          value={hint}
          onChange={e => setHint(e.target.value as ExtractionSourceHint)}
          className="w-full h-9 px-3 text-[13px] rounded-md bg-gray-50 dark:bg-gray-800/50 border border-gray-200 dark:border-gray-800"
          data-testid="extraction-hint-picker"
        >
          {HINT_OPTIONS.map(o => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>
      </div>

      <div>
        <label className="block text-[10px] uppercase tracking-wider font-semibold text-gray-500 dark:text-gray-400 mb-1.5">
          Arquivo (PNG, JPG, WEBP, PDF, CSV — máx 10 MB)
        </label>
        <label
          className="flex items-center justify-center gap-2 px-3 py-6 rounded-lg border-2 border-dashed border-gray-200 dark:border-gray-700 hover:border-indigo-500 hover:bg-indigo-50/40 dark:hover:bg-indigo-900/10 cursor-pointer transition-colors"
          data-testid="extraction-dropzone"
        >
          <input
            type="file"
            accept={ACCEPTED_MIME}
            onChange={e => setFile(e.target.files?.[0] ?? null)}
            className="hidden"
            data-testid="extraction-file-input"
          />
          <Upload className="w-4 h-4 text-gray-400" />
          <span className="text-[12px] text-gray-600 dark:text-gray-300">
            {file ? file.name : 'Clique ou arraste para selecionar'}
          </span>
        </label>
      </div>

      {error && (
        <div className="text-[12px] text-red-600 dark:text-red-400" data-testid="extraction-error">
          {error}
        </div>
      )}
    </div>
  )
}


function ReviewStage({ job, error }: { job: ExtractionJobOut; error: string | null }) {
  const payload = job.extracted_json
  // Specialised renderers for the V1 hints; everything else falls back to JSON.
  if (job.source_hint === 'SCREENSHOT_PRICE' && payload && 'price' in payload) {
    return (
      <div className="space-y-3" data-testid="extraction-review">
        <div className="flex items-center justify-between">
          <div className="text-[12px] font-semibold text-gray-900 dark:text-white">Cotação extraída</div>
          <ConfidencePill value={job.confidence} />
        </div>
        <dl className="grid grid-cols-2 gap-3 text-[12px]">
          <Field label="Ticker" value={String(payload.ticker ?? '—')} mono />
          <Field label="Preço" value={`${payload.currency ?? 'BRL'} ${Number(payload.price).toFixed(2)}`} tnum />
          <Field label="Source" value={String(payload.source_app ?? '—')} />
          <Field label="Quando" value={String(payload.as_of_timestamp ?? '—')} mono />
        </dl>
        {error && <div className="text-[11px] text-red-500">{error}</div>}
      </div>
    )
  }
  if (job.source_hint === 'BROKER_POSITION' && payload && Array.isArray((payload as { positions?: unknown[] }).positions)) {
    const positions = (payload as { positions: Array<Record<string, unknown>> }).positions
    return (
      <div className="space-y-3" data-testid="extraction-review">
        <div className="flex items-center justify-between">
          <div className="text-[12px] font-semibold text-gray-900 dark:text-white">
            {positions.length} posiç{positions.length === 1 ? 'ão' : 'ões'} extraída{positions.length === 1 ? '' : 's'}
          </div>
          <ConfidencePill value={job.confidence} />
        </div>
        <table className="w-full text-[11px]">
          <thead>
            <tr className="text-[10px] uppercase tracking-wider text-gray-500 border-b border-gray-200 dark:border-gray-800">
              <th className="px-2 py-1 text-left">Ticker</th>
              <th className="px-2 py-1 text-right">Qtd</th>
              <th className="px-2 py-1 text-right">Preço</th>
              <th className="px-2 py-1 text-center">Confiança</th>
            </tr>
          </thead>
          <tbody>
            {positions.map((p, i) => (
              <tr key={i} className="border-b border-gray-100 dark:border-gray-900">
                <td className="px-2 py-1 font-mono">{String(p.ticker_normalized ?? p.ticker_raw ?? '—')}</td>
                <td className="px-2 py-1 tnum text-right">{String(p.quantity ?? '—')}</td>
                <td className="px-2 py-1 tnum text-right">{Number(p.unit_price ?? 0).toFixed(2)}</td>
                <td className="px-2 py-1 text-center">
                  <ConfidencePill value={typeof p.confidence === 'number' ? p.confidence : null} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {error && <div className="text-[11px] text-red-500">{error}</div>}
      </div>
    )
  }
  return (
    <div className="space-y-2" data-testid="extraction-review">
      <div className="flex items-center justify-between">
        <div className="text-[12px] font-semibold text-gray-900 dark:text-white">JSON extraído</div>
        <ConfidencePill value={job.confidence} />
      </div>
      <pre className="text-[10px] font-mono p-2 rounded bg-gray-50 dark:bg-gray-800 overflow-auto max-h-80">
        {JSON.stringify(payload, null, 2)}
      </pre>
      {error && <div className="text-[11px] text-red-500">{error}</div>}
    </div>
  )
}


function Field({ label, value, mono, tnum }: { label: string; value: string; mono?: boolean; tnum?: boolean }) {
  return (
    <div>
      <dt className="text-[10px] uppercase tracking-wider text-gray-500 dark:text-gray-400">{label}</dt>
      <dd className={`text-[12px] font-medium text-gray-900 dark:text-white ${mono ? 'font-mono' : ''} ${tnum ? 'tnum' : ''}`}>
        {value}
      </dd>
    </div>
  )
}
