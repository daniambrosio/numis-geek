/* Full asset detail page — matches prototypes/index.html AtivoDetailPage. */
import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { ArrowLeft, Plus, Settings } from 'lucide-react'
import {
  api,
  type AssetMovementOut,
  type AssetOut,
  type DistributionOut,
  type FinancialInstitutionOut,
  type PositionOut,
  type UserOut,
} from '../lib/api'
import AppLayout from '../components/AppLayout'
import OpenOptionsCard from '../components/OpenOptionsCard'
import OptionModal from '../components/OptionModal'
import {
  Card, CcyPill, ClassBadge, FILogo, SectionTitle, TypeBadge,
} from '../components/ui'
import { KLASS, collapsedOf } from '../lib/tokens'

function fmtMoney(n: number | null | undefined, ccy: string, opts: { sign?: boolean; compact?: boolean } = {}) {
  if (n == null) return '—'
  const v = opts.sign ? Math.abs(n) : n
  const sign = opts.sign && n > 0 ? '+ ' : opts.sign && n < 0 ? '− ' : ''
  if (opts.compact && Math.abs(v) >= 1000) {
    return sign + v.toLocaleString('pt-BR', { style: 'currency', currency: ccy, notation: 'compact', maximumFractionDigits: 1 })
  }
  return sign + v.toLocaleString('pt-BR', { style: 'currency', currency: ccy })
}

function fmtBRL(n: number | null | undefined, opts: { sign?: boolean; compact?: boolean } = {}) {
  return fmtMoney(n, 'BRL', opts)
}

function fmtNum(n: number | null | undefined, digits = 2) {
  if (n == null) return '—'
  return n.toLocaleString('pt-BR', { maximumFractionDigits: digits })
}

function fmtPct(n: number | null | undefined, digits = 2, sign = false) {
  if (n == null) return '—'
  const v = n * 100
  return (sign && v > 0 ? '+' : '') + v.toFixed(digits) + '%'
}

function fmtDate(iso: string) {
  return new Intl.DateTimeFormat('pt-BR').format(new Date(iso + (iso.length === 10 ? 'T00:00:00' : '')))
}

export default function AssetDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [me, setMe] = useState<UserOut | null>(null)
  const [asset, setAsset] = useState<AssetOut | null>(null)
  const [fi, setFi] = useState<FinancialInstitutionOut | null>(null)
  const [position, setPosition] = useState<PositionOut | null>(null)
  const [movements, setMovements] = useState<AssetMovementOut[]>([])
  const [distributions, setDistributions] = useState<DistributionOut[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [optionModalOpen, setOptionModalOpen] = useState(false)
  const [optionsRefresh, setOptionsRefresh] = useState(0)

  useEffect(() => {
    api.me().then(setMe).catch(() => navigate('/login'))
  }, [navigate])

  useEffect(() => {
    if (!me || !id) return
    setLoading(true)
    setError('')
    api.getAsset(id)
      .then(async a => {
        setAsset(a)
        // Hydrate FI via account → financial_institution
        const fis = await api.listFinancialInstitutions().catch(() => [])
        const account = await api.getAccount(a.account_id).catch(() => null)
        if (account) {
          setFi(fis.find(f => f.id === account.financial_institution_id) ?? null)
        }
      })
      .then(() => Promise.all([
        api.getAssetPosition(id).catch(() => null),
        api.listAssetMovementsForAsset(id, { page: 1, page_size: 200, include_inactive: false })
          .then(p => p.items).catch(() => [] as AssetMovementOut[]),
        api.listDistributionsForAsset(id, { page: 1, page_size: 200, include_inactive: false })
          .then(p => p.items).catch(() => [] as DistributionOut[]),
      ]))
      .then(([pos, movs, dists]) => {
        setPosition(pos)
        setMovements(movs)
        setDistributions(dists)
      })
      .catch(e => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false))
  }, [me, id])

  const distTotalBRL = useMemo(
    () => distributions.reduce((s, d) => s + d.net_amount * (d.fx_rate || 1), 0),
    [distributions],
  )

  if (!me) return null
  if (loading) {
    return (
      <AppLayout user={me}>
        <div className="text-sm text-gray-400 py-16 text-center">Carregando…</div>
      </AppLayout>
    )
  }
  if (error || !asset) {
    return (
      <AppLayout user={me}>
        <Card>
          <div className="text-sm text-red-500 py-6 text-center">{error || 'Ativo não encontrado.'}</div>
        </Card>
      </AppLayout>
    )
  }

  const klass = collapsedOf(asset.asset_class)
  const klassColor = KLASS[klass].color
  const ccy = asset.currency
  const qty = position?.quantity_held ?? 0
  const avg = position?.average_cost ?? null
  const price = position?.current_price ?? asset.current_price ?? null
  const value = price != null && qty ? price * qty : null
  const cost = avg != null && qty ? avg * qty : null
  const pl = value != null && cost != null ? value - cost : null
  const variation = position?.variation ?? null
  const rentabilidade = position?.rentabilidade ?? null
  const investedBRL = position?.total_invested_brl ?? null
  const yoc = (investedBRL && investedBRL > 0) ? distTotalBRL / investedBRL : null
  const valueBRL = position?.current_value_brl ?? null
  const dy = (valueBRL && valueBRL > 0) ? distTotalBRL / valueBRL : null

  return (
    <AppLayout user={me}>
      <div className="space-y-6">
        {/* Back link */}
        <button
          onClick={() => navigate('/assets')}
          className="inline-flex items-center gap-1.5 text-[11px] text-gray-500 hover:text-gray-700 dark:hover:text-gray-300"
        >
          <ArrowLeft className="w-3.5 h-3.5" /> Voltar pra Ativos
        </button>

        {/* Header */}
        <Card padding="p-6">
          <div className="flex items-start gap-4">
            <span className="w-1.5 h-14 rounded-full" style={{ background: klassColor }} />
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                <h1 className="text-3xl font-mono font-semibold text-gray-900 dark:text-white">
                  {asset.ticker || asset.name}
                </h1>
                <ClassBadge klass={klass} size="xs" withDot={false} />
                <CcyPill ccy={ccy} />
                {!asset.is_active && (
                  <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium uppercase tracking-wider bg-gray-200 dark:bg-gray-800 text-gray-500">
                    Inativo
                  </span>
                )}
              </div>
              <div className="text-sm text-gray-500 mt-1">{asset.name}</div>
              {fi && (
                <div className="mt-2 flex items-center gap-2 text-[12px] text-gray-500">
                  <FILogo slug={fi.logo_slug} shortName={fi.short_name} size="sm" />
                  <span>{fi.long_name}</span>
                </div>
              )}
            </div>
            <div className="flex items-center gap-2 shrink-0">
              <button className="h-8 px-3 inline-flex items-center gap-1.5 rounded-lg text-[12px] bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700 transition-colors">
                <Settings className="w-3.5 h-3.5" /> Editar
              </button>
              {asset.asset_class !== 'OPTION' && (
                <button
                  onClick={() => setOptionModalOpen(true)}
                  className="h-8 px-3 inline-flex items-center gap-1.5 rounded-lg text-[12px] text-white transition-colors"
                  style={{ background: KLASS.OPTION.color }}
                >
                  <Plus className="w-3.5 h-3.5" /> Opção
                </button>
              )}
            </div>
          </div>

          {/* KPI grid 4×2 */}
          <div className="mt-6 grid grid-cols-2 lg:grid-cols-4 gap-3">
            <KpiTile
              label="Posição"
              value={value != null ? fmtMoney(value, ccy, { compact: true }) : '—'}
              sub={`${fmtNum(qty, qty < 1 ? 6 : 2)} unidades`}
            />
            <KpiTile label="Preço médio" value={avg != null ? fmtMoney(avg, ccy) : '—'} />
            <KpiTile
              label="Preço atual"
              value={price != null ? fmtMoney(price, ccy) : '—'}
              sub={asset.price_updated_at
                ? `atualizado · ${new Date(asset.price_updated_at).toLocaleDateString('pt-BR')}`
                : 'sem preço atual'}
            />
            <KpiTile
              label="P&L"
              value={pl != null ? fmtMoney(pl, ccy, { sign: true, compact: true }) : '—'}
              intent={pl == null ? undefined : pl >= 0 ? 'positive' : 'negative'}
            />
            <KpiTile
              label="Variação"
              value={fmtPct(variation, 2, true)}
              sub="apenas preço"
              intent={variation == null ? undefined : variation >= 0 ? 'positive' : 'negative'}
            />
            <KpiTile
              label="Rentabilidade"
              value={fmtPct(rentabilidade, 2, true)}
              sub="preço + proventos"
              intent={rentabilidade == null ? undefined : rentabilidade >= 0 ? 'positive' : 'negative'}
            />
            <KpiTile
              label="YoC"
              value={fmtPct(yoc, 1)}
              sub={fmtBRL(distTotalBRL, { compact: true })}
              intent={yoc != null && yoc > 0 ? 'positive' : undefined}
            />
            <KpiTile label="DY" value={fmtPct(dy, 1)} sub="anualizado" />
          </div>
        </Card>

        {/* Open options card (only for underlying-eligible assets) */}
        {asset.asset_class !== 'OPTION' && (
          <OpenOptionsCard
            key={optionsRefresh}
            underlyingId={asset.id}
            underlyingTicker={asset.ticker || asset.name}
            onAction={() => setOptionsRefresh(n => n + 1)}
          />
        )}

        {/* Lançamentos full table */}
        <Card>
          <SectionTitle action={
            <button className="h-7 px-2.5 inline-flex items-center gap-1 rounded-md text-[11px] font-medium bg-indigo-500 hover:bg-indigo-400 text-white transition-colors">
              <Plus className="w-3 h-3" /> Novo lançamento
            </button>
          }>
            Lançamentos · {movements.length}
          </SectionTitle>
          {movements.length === 0 ? (
            <div className="text-[12px] text-gray-500 italic py-6 text-center">Sem lançamentos.</div>
          ) : (
            <div className="overflow-x-auto -mx-1">
              <table className="w-full text-[12px]">
                <thead>
                  <tr className="text-[10px] uppercase tracking-wider text-gray-500">
                    <th className="text-left font-medium px-2 py-2">Data</th>
                    <th className="text-left font-medium px-2 py-2">Tipo</th>
                    <th className="text-right font-medium px-2 py-2">Qtd</th>
                    <th className="text-right font-medium px-2 py-2">Preço</th>
                    <th className="text-right font-medium px-2 py-2">Taxa</th>
                    <th className="text-right font-medium px-2 py-2">Net</th>
                  </tr>
                </thead>
                <tbody>
                  {movements.map(m => (
                    <tr key={m.id} className="border-t border-gray-100 dark:border-gray-800 hover:bg-gray-50 dark:hover:bg-gray-800/30">
                      <td className="px-2 py-2 tnum text-gray-400">{fmtDate(m.event_date)}</td>
                      <td className="px-2"><TypeBadge code={m.type} label={m.type_label} /></td>
                      <td className="px-2 text-right tnum">{fmtNum(m.quantity, 6)}</td>
                      <td className="px-2 text-right tnum money text-gray-400">{fmtMoney(m.unit_price, m.currency)}</td>
                      <td className="px-2 text-right tnum money text-gray-500">{m.fee ? fmtMoney(m.fee, m.currency) : '—'}</td>
                      <td className="px-2 text-right">
                        <div className={`tnum money font-medium ${m.net_amount < 0 ? 'text-red-500 dark:text-red-400' : m.net_amount > 0 ? 'text-emerald-500 dark:text-emerald-400' : 'text-gray-500'}`}>
                          {fmtMoney(m.net_amount, m.currency, { sign: true })}
                        </div>
                        <CcyPill ccy={m.currency} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>

        {/* Proventos full table */}
        <Card>
          <SectionTitle action={
            <span className="text-[11px] tnum text-gray-500">
              Total <span className="money text-emerald-500 dark:text-emerald-400 font-medium">{fmtBRL(distTotalBRL, { compact: true })}</span>
            </span>
          }>
            Proventos · {distributions.length}
          </SectionTitle>
          {distributions.length === 0 ? (
            <div className="text-[12px] text-gray-500 italic py-6 text-center">Sem proventos.</div>
          ) : (
            <div className="overflow-x-auto -mx-1">
              <table className="w-full text-[12px]">
                <thead>
                  <tr className="text-[10px] uppercase tracking-wider text-gray-500">
                    <th className="text-left font-medium px-2 py-2">Data</th>
                    <th className="text-left font-medium px-2 py-2">Tipo</th>
                    <th className="text-right font-medium px-2 py-2">Bruto</th>
                    <th className="text-right font-medium px-2 py-2">IR</th>
                    <th className="text-right font-medium px-2 py-2">Líquido</th>
                  </tr>
                </thead>
                <tbody>
                  {distributions.map(d => (
                    <tr key={d.id} className="border-t border-gray-100 dark:border-gray-800 hover:bg-gray-50 dark:hover:bg-gray-800/30">
                      <td className="px-2 py-2 tnum text-gray-400">{fmtDate(d.event_date)}</td>
                      <td className="px-2"><TypeBadge code={d.type} label={d.type_label} /></td>
                      <td className="px-2 text-right tnum money text-gray-400">{fmtMoney(d.gross_amount, d.currency)}</td>
                      <td className="px-2 text-right tnum money text-amber-500 dark:text-amber-400">{d.tax ? '− ' + fmtMoney(d.tax, d.currency) : '—'}</td>
                      <td className="px-2 text-right">
                        <div className="tnum money font-medium text-emerald-500 dark:text-emerald-400">
                          {fmtMoney(d.net_amount, d.currency, { sign: true })}
                        </div>
                        <CcyPill ccy={d.currency} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>

        {/* Detalhes */}
        <Card>
          <SectionTitle>Detalhes</SectionTitle>
          <dl className="grid grid-cols-2 lg:grid-cols-4 gap-x-6 gap-y-3 text-[12px]">
            <Detail label="Ticker" value={asset.ticker || '—'} mono />
            <Detail label="CNPJ" value={asset.cnpj || '—'} mono />
            <Detail label="Classe" value={KLASS[klass].label} />
            <Detail label="País" value={asset.country || '—'} />
            <Detail label="Origem" value={asset.external_source ?? 'manual'} />
            <Detail label="Criado" value={new Date(asset.created_at).toLocaleDateString('pt-BR')} />
            <Detail label="Atualizado" value={new Date(asset.updated_at).toLocaleDateString('pt-BR')} />
            <Detail label="Status" value={asset.is_active ? 'Ativo' : 'Inativo'} />
          </dl>
          {asset.notes && (
            <div className="mt-4">
              <div className="text-[10px] font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-2">Notas</div>
              <p className="text-[12px] text-gray-700 dark:text-gray-300 whitespace-pre-wrap">{asset.notes}</p>
            </div>
          )}
        </Card>
      </div>

      {optionModalOpen && (
        <OptionModal
          underlying={asset}
          onClose={() => setOptionModalOpen(false)}
          onSaved={() => setOptionsRefresh(n => n + 1)}
        />
      )}
    </AppLayout>
  )
}

function KpiTile({
  label, value, sub, intent,
}: { label: string; value: string; sub?: string; intent?: 'positive' | 'negative' }) {
  const valueCls =
    value === '—'
      ? 'text-gray-300 dark:text-gray-700'
      : intent === 'positive' ? 'text-emerald-500 dark:text-emerald-400'
      : intent === 'negative' ? 'text-red-500 dark:text-red-400'
      : 'text-gray-900 dark:text-white'
  return (
    <div className="rounded-xl bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 px-4 py-3">
      <div className="text-[10px] uppercase tracking-wider font-medium text-gray-500 dark:text-gray-400">{label}</div>
      <div className={`mt-1 text-xl font-semibold tnum money ${valueCls}`}>{value}</div>
      {sub && <div className="text-[11px] text-gray-400 dark:text-gray-500 tnum mt-0.5">{sub}</div>}
    </div>
  )
}

function Detail({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div>
      <dt className="text-[10px] uppercase tracking-wider text-gray-500 dark:text-gray-400">{label}</dt>
      <dd className={`text-[12px] mt-0.5 ${mono ? 'font-mono' : ''} text-gray-900 dark:text-white`}>{value}</dd>
    </div>
  )
}
