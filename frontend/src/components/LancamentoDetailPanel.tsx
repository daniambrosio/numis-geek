import { useEffect } from 'react'
import { X } from 'lucide-react'
import {
  type AssetOut, type FinancialInstitutionOut, type LancamentoOut,
} from '../lib/api'
import { KLASS, collapsedOf, lanTypeColor } from '../lib/tokens'
import { CcyPill, ClassBadge, FILogo, TypeBadge } from './ui'

interface Props {
  lancamento: LancamentoOut
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

function fmtNum(n: number | null | undefined, digits = 8) {
  if (n == null) return '—'
  return n.toLocaleString('pt-BR', { maximumFractionDigits: digits })
}

export default function LancamentoDetailPanel({
  lancamento: l, asset, fi, onClose, onEdit, onDeactivate,
}: Props) {
  useEffect(() => {
    function onEsc(e: KeyboardEvent) { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onEsc)
    return () => document.removeEventListener('keydown', onEsc)
  }, [onClose])

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

          {/* Notes */}
          <div>
            <div className="text-[10px] font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-2">
              Notas
            </div>
            {l.notes ? (
              <p className="text-[12px] text-gray-700 dark:text-gray-300 whitespace-pre-wrap">{l.notes}</p>
            ) : (
              <p className="text-[12px] text-gray-400 dark:text-gray-600">—</p>
            )}
            <div className="text-[10px] text-gray-400 dark:text-gray-600 mt-3">
              Anexos chegam com spec 15 (Attachment polimórfica).
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="px-5 py-3 border-t border-gray-200 dark:border-gray-800 flex items-center justify-end gap-2">
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
