import { useEffect, useState } from 'react'
import { X } from 'lucide-react'
import {
  api, type AssetOut, type FinancialInstitutionOut, type AssetMovementOut,
  type PositionOut,
} from '../lib/api'
import { KLASS, collapsedOf } from '../lib/tokens'
import { ClassBadge, CcyPill, FILogo } from './ui'

interface Props {
  asset: AssetOut
  fi: FinancialInstitutionOut | null
  onClose: () => void
  onEdit: () => void
  onDeactivate: () => void
}

function fmtNumber(n: number | null | undefined, digits = 8) {
  if (n == null) return '—'
  return n.toLocaleString('pt-BR', { maximumFractionDigits: digits })
}

function fmtMoney(n: number | null | undefined, currency: string) {
  if (n == null) return '—'
  return n.toLocaleString('pt-BR', { style: 'currency', currency })
}

export default function AssetDetailPanel({ asset, fi, onClose, onEdit, onDeactivate }: Props) {
  const [position, setPosition] = useState<PositionOut | null>(null)
  const [recent, setRecent] = useState<AssetMovementOut[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancel = false
    Promise.all([
      api.getAssetPosition(asset.id).catch(() => null),
      api.listAssetMovementsForAsset(asset.id, { page: 1, page_size: 5, include_inactive: false })
        .then(p => p.items)
        .catch(() => []),
    ]).then(([pos, recs]) => {
      if (cancel) return
      setPosition(pos)
      setRecent(recs)
      setLoading(false)
    })
    return () => { cancel = true }
  }, [asset.id])

  useEffect(() => {
    function onEsc(e: KeyboardEvent) { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onEsc)
    return () => document.removeEventListener('keydown', onEsc)
  }, [onClose])

  const klass = collapsedOf(asset.asset_class)
  const klassColor = KLASS[klass].color

  return (
    <div className="fixed inset-0 z-50">
      <div className="absolute inset-0 bg-black/50 backdrop-blur-[2px]" onClick={onClose} />
      <aside className="absolute right-0 top-0 h-full w-full sm:w-[520px] bg-gray-50 dark:bg-gray-950 border-l border-gray-200 dark:border-gray-800 shadow-2xl overflow-y-auto scrollbar-thin flex flex-col">
        {/* Sticky header */}
        <div className="sticky top-0 z-10 bg-gray-50 dark:bg-gray-950 border-b border-gray-200 dark:border-gray-800 px-5 py-3.5 flex items-center justify-between gap-3">
          <div className="min-w-0 flex-1 flex items-center gap-2">
            <span className="w-1.5 h-8 rounded-full shrink-0" style={{ background: klassColor }} />
            <div className="min-w-0">
              <div className="text-[10px] uppercase tracking-wider text-gray-500 flex items-center gap-1.5">
                <ClassBadge klass={klass} size="xs" withDot={false} />
                <CcyPill ccy={asset.currency} />
              </div>
              <div className="text-sm font-semibold truncate text-gray-900 dark:text-white">
                {asset.ticker ? <span className="font-mono">{asset.ticker} </span> : null}
                {asset.name}
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
          {/* Custodian */}
          {fi && (
            <div className="flex items-center gap-2">
              <FILogo slug={fi.logo_slug} shortName={fi.short_name} size="sm" />
              <div>
                <div className="text-[11px] text-gray-500 dark:text-gray-400 uppercase tracking-wider">Custódia</div>
                <div className="text-[13px] text-gray-900 dark:text-white">{fi.short_name}</div>
              </div>
            </div>
          )}

          {/* KPIs */}
          <div className="grid grid-cols-2 gap-3">
            <Kpi label="Posição" value={loading ? '…' : fmtNumber(position?.quantity_held ?? null)} />
            <Kpi label={`Preço médio (${asset.currency})`} value={loading ? '…' : fmtNumber(position?.average_cost ?? null, 4)} />
            <Kpi label="Total investido (BRL)" money value={loading ? '…' : fmtMoney(position?.total_invested_brl ?? null, 'BRL')} />
            <Kpi label="Total recebido (BRL)" money value={loading ? '…' : fmtMoney(position?.total_received_brl ?? null, 'BRL')} />
            <Kpi
              label={`Preço atual (${asset.currency})`}
              value={loading ? '…' : fmtMoney(position?.current_price ?? null, asset.currency)}
              money
              hint={asset.price_updated_at ? `atualizado em ${new Date(asset.price_updated_at).toLocaleDateString('pt-BR')}` : 'sem preço atual ainda — edite o ativo'}
            />
            <Kpi
              label="Variação"
              value={position?.variation == null ? '—' : `${position.variation >= 0 ? '+' : ''}${(position.variation * 100).toFixed(2)}%`}
              tone={position?.variation == null ? undefined : position.variation >= 0 ? 'positive' : 'negative'}
            />
            <Kpi
              label="Valor atual (asset ccy)"
              value={position?.current_value == null ? '—' : fmtMoney(position.current_value, asset.currency)}
              money
            />
            <Kpi
              label="Rentabilidade"
              value={position?.rentabilidade == null ? '—' : `${position.rentabilidade >= 0 ? '+' : ''}${(position.rentabilidade * 100).toFixed(2)}%`}
              tone={position?.rentabilidade == null ? undefined : position.rentabilidade >= 0 ? 'positive' : 'negative'}
              hint="Variação + proventos recebidos"
            />
          </div>

          {/* Recent */}
          <div>
            <div className="text-[10px] font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-2">
              Lançamentos recentes
            </div>
            {loading ? (
              <div className="text-xs text-gray-400 dark:text-gray-600">Carregando…</div>
            ) : recent.length === 0 ? (
              <div className="text-xs text-gray-400 dark:text-gray-600">Sem lançamentos.</div>
            ) : (
              <ul className="space-y-1.5">
                {recent.map(l => (
                  <li key={l.id} className="flex items-center justify-between gap-3 text-[12px]">
                    <div className="flex items-center gap-2 min-w-0">
                      <span className="text-gray-400 dark:text-gray-500 tnum shrink-0">{l.event_date}</span>
                      <span className="text-gray-700 dark:text-gray-300 truncate">{l.type_label}</span>
                    </div>
                    <span className="font-medium text-gray-900 dark:text-white tnum shrink-0">
                      <span className="money">{fmtMoney(l.net_amount, l.currency)}</span>
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>

          {/* Details */}
          <div>
            <div className="text-[10px] font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-2">
              Detalhes
            </div>
            <dl className="space-y-1.5 text-[12px]">
              <Detail label="CNPJ" value={asset.cnpj ?? '—'} />
              <Detail label="Origem" value={asset.external_source ?? 'manual'} />
              <Detail label="Criado" value={new Date(asset.created_at).toLocaleDateString('pt-BR')} />
              <Detail label="Atualizado" value={new Date(asset.updated_at).toLocaleDateString('pt-BR')} />
            </dl>
            {asset.notes && (
              <div className="mt-3">
                <div className="text-[10px] font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1">
                  Notas
                </div>
                <p className="text-[12px] text-gray-700 dark:text-gray-300 whitespace-pre-wrap">{asset.notes}</p>
              </div>
            )}
          </div>
        </div>

        {/* Footer */}
        <div className="px-5 py-3 border-t border-gray-200 dark:border-gray-800 flex items-center justify-end gap-2">
          {asset.is_active && (
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

function Kpi({
  label, value, money, hint, tone,
}: {
  label: string
  value: string
  money?: boolean
  hint?: string
  tone?: 'positive' | 'negative'
}) {
  const valueCls = value === '—' || value === '…'
    ? 'text-gray-300 dark:text-gray-700'
    : tone === 'positive' ? 'text-emerald-500 dark:text-emerald-400'
    : tone === 'negative' ? 'text-red-500 dark:text-red-400'
    : 'text-gray-900 dark:text-white'
  return (
    <div className="px-3 py-2 rounded-xl bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800" title={hint}>
      <div className="text-[10px] uppercase tracking-wider font-medium text-gray-500 dark:text-gray-400">{label}</div>
      <div className={`mt-1 text-[14px] font-semibold tnum ${valueCls}`}>
        {money ? <span className="money">{value}</span> : value}
      </div>
    </div>
  )
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-3">
      <dt className="text-gray-500 dark:text-gray-400">{label}</dt>
      <dd className="text-gray-700 dark:text-gray-300 text-right truncate">{value}</dd>
    </div>
  )
}
