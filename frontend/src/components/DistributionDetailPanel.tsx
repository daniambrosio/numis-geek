import { useEffect } from 'react'
import { X } from 'lucide-react'
import {
  type AssetOut, type DistributionOut, type FinancialInstitutionOut,
} from '../lib/api'
import { KLASS, collapsedOf } from '../lib/tokens'
import { CcyPill, ClassBadge, FILogo } from './ui'

interface Props {
  distribution: DistributionOut
  asset: AssetOut | null
  fi: FinancialInstitutionOut | null
  onClose: () => void
  onEdit: () => void
  onDeactivate: () => void
}

function fmtMoney(n: number | null | undefined, currency: string, opts: { sign?: boolean } = {}) {
  if (n == null) return '—'
  const v = opts.sign ? Math.abs(n) : n
  const sign = opts.sign && n > 0 ? '+ ' : opts.sign && n < 0 ? '− ' : ''
  return sign + v.toLocaleString('pt-BR', { style: 'currency', currency })
}

const TYPE_COLOR: Record<string, string> = {
  DIVIDEND: '#22c55e',
  INTEREST: '#3b82f6',
  JCP: '#f59e0b',
  SECURITIES_LENDING: '#8b5cf6',
}

export default function DistributionDetailPanel({
  distribution: d, asset, fi, onClose, onEdit, onDeactivate,
}: Props) {
  useEffect(() => {
    function onEsc(e: KeyboardEvent) { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onEsc)
    return () => document.removeEventListener('keydown', onEsc)
  }, [onClose])

  const typeColor = TYPE_COLOR[d.type] || '#9ca3af'
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
                <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] uppercase tracking-wider bg-amber-500/15 text-amber-700 dark:text-amber-400">
                  {d.type_label}
                </span>
                <CcyPill ccy={d.currency} />
              </div>
              <div className="text-sm font-semibold truncate text-gray-900 dark:text-white">
                {asset ? (
                  <>
                    {asset.ticker && <span className="font-mono">{asset.ticker} </span>}
                    {asset.name}
                  </>
                ) : (
                  <span className="italic text-gray-500">Sem ticker · via {fi?.short_name}</span>
                )}
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
          {/* Asset / FI summary */}
          <div className="rounded-xl bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 p-3 flex items-center gap-3">
            <span
              className="w-1 h-10 rounded-full shrink-0"
              style={{ background: klass ? KLASS[klass].color : '#94a3b8' }}
            />
            <div className="min-w-0 flex-1">
              {asset ? (
                <>
                  <div className="flex items-center gap-2">
                    {asset.ticker && (
                      <span className="font-mono text-[12px] font-medium text-gray-900 dark:text-white">{asset.ticker}</span>
                    )}
                    {klass && <ClassBadge klass={klass} size="xs" withDot={false} />}
                  </div>
                  <div className="text-[11px] text-gray-500 dark:text-gray-400 truncate">{asset.name}</div>
                </>
              ) : (
                <>
                  <div className="text-[12px] italic text-gray-500">Sem ticker</div>
                  <div className="text-[11px] text-gray-500 dark:text-gray-400 truncate">
                    Provento genérico via instituição
                  </div>
                </>
              )}
            </div>
            {fi && (
              <div className="flex items-center gap-1.5 shrink-0">
                <FILogo slug={fi.logo_slug} shortName={fi.short_name} size="sm" />
                <span className="text-[11px] text-gray-500 dark:text-gray-400">{fi.short_name}</span>
              </div>
            )}
          </div>

          {/* Fields grid */}
          <dl className="grid grid-cols-2 gap-3 text-[12px]">
            <Field label="Data" value={d.event_date} mono />
            <Field label="Moeda" value={d.currency} />
            <Field label="Bruto" value={fmtMoney(d.gross_amount, d.currency)} money tnum />
            <Field
              label="IR retido"
              value={d.tax && d.tax > 0 ? fmtMoney(d.tax, d.currency) : '—'}
              money tnum
            />
            <Field
              label="Líquido"
              value={fmtMoney(d.net_amount, d.currency, { sign: true })}
              money tnum
              tone={d.net_amount > 0 ? 'positive' : d.net_amount < 0 ? 'negative' : undefined}
            />
            <Field
              label="FX rate"
              value={d.currency === 'USD' ? `R$ ${Number(d.fx_rate).toFixed(4)}` : '—'}
              tnum
            />
            <Field label="Origem" value={d.external_source ?? 'manual'} />
            <Field label="Status" value={d.is_active ? 'Ativo' : 'Inativo'} />
          </dl>

          {/* Notes */}
          <div>
            <div className="text-[10px] font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-2">
              Notas
            </div>
            {d.notes ? (
              <p className="text-[12px] text-gray-700 dark:text-gray-300 whitespace-pre-wrap">{d.notes}</p>
            ) : (
              <p className="text-[12px] text-gray-400 dark:text-gray-600">—</p>
            )}
          </div>
        </div>

        {/* Footer */}
        <div className="px-5 py-3 border-t border-gray-200 dark:border-gray-800 flex items-center justify-end gap-2">
          {d.is_active && (
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
      </aside>
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
  return (
    <div>
      <dt className="text-[10px] uppercase tracking-wider text-gray-500 dark:text-gray-400 font-medium mb-0.5">
        {label}
      </dt>
      <dd
        className={`${mono ? 'font-mono' : ''} ${money ? 'money' : ''} ${tnum ? 'tnum' : ''} ${
          tone === 'positive' ? 'text-emerald-500 dark:text-emerald-400' :
          tone === 'negative' ? 'text-red-500 dark:text-red-400' :
          'text-gray-700 dark:text-gray-300'
        }`}
      >
        {value}
      </dd>
    </div>
  )
}
