/* Full asset detail page — mirrors prototypes/index.html `AtivoDetailPage`
 * (line 3274). Same structure, classes, spacing and helpers. */
import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { ArrowLeft, Coins, MoreHorizontal, Plus, Settings } from 'lucide-react'
import {
  api,
  type AccountOut,
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
import Sparkline from '../components/Sparkline'
import {
  Card, CcyPill, ClassBadge, FILogo, SectionTitle,
} from '../components/ui'
import { KLASS, collapsedOf } from '../lib/tokens'

// ── Formatters (match prototype) ─────────────────────────────────────────────

function fmtBRL(n: number | null | undefined, opts: { compact?: boolean; sign?: boolean } = {}) {
  if (n == null) return '—'
  const { compact = false, sign = false } = opts
  const formatter = new Intl.NumberFormat('pt-BR', {
    style: 'currency', currency: 'BRL',
    minimumFractionDigits: compact ? 0 : 2,
    maximumFractionDigits: compact ? 0 : 2,
    notation: compact ? 'compact' : 'standard',
  })
  const out = formatter.format(Math.abs(n))
  if (sign) return (n >= 0 ? '+' : '−') + out.replace('R$', 'R$ ')
  return n < 0 ? '−' + out : out
}

function fmtUSD(n: number | null | undefined, opts: { compact?: boolean; sign?: boolean } = {}) {
  if (n == null) return '—'
  const { compact = false, sign = false } = opts
  const formatter = new Intl.NumberFormat('en-US', {
    style: 'currency', currency: 'USD',
    minimumFractionDigits: compact ? 0 : 2,
    maximumFractionDigits: compact ? 0 : 2,
    notation: compact ? 'compact' : 'standard',
  })
  const out = formatter.format(Math.abs(n))
  if (sign) return (n >= 0 ? '+' : '−') + out
  return n < 0 ? '−' + out : out
}

function fmtMoney(n: number | null | undefined, ccy: string, opts?: { compact?: boolean; sign?: boolean }) {
  return ccy === 'USD' ? fmtUSD(n, opts) : fmtBRL(n, opts)
}

function fmtNum(n: number | null | undefined, dp = 0) {
  if (n == null) return '—'
  return new Intl.NumberFormat('pt-BR', { minimumFractionDigits: dp, maximumFractionDigits: dp }).format(n)
}

function fmtPct(n: number | null | undefined, dp = 1, sign = false) {
  if (n == null) return '—'
  const v = (n * 100).toFixed(dp)
  return (sign && n > 0 ? '+' : '') + v + '%'
}

function fmtDate(iso: string) {
  return new Intl.DateTimeFormat('pt-BR').format(new Date(iso + (iso.length === 10 ? 'T00:00:00' : '')))
}

function fmtRelDate(iso: string) {
  const d = new Date(iso)
  const today = new Date()
  const diff = Math.round((today.getTime() - d.getTime()) / (1000 * 60 * 60 * 24))
  if (diff === 0) return 'Hoje'
  if (diff === 1) return 'Ontem'
  if (diff < 7) return `Há ${diff} dias`
  return fmtDate(iso)
}

function CountryFlag({ country }: { country: string }) {
  const flag = country === 'BR' ? '🇧🇷' : country === 'US' ? '🇺🇸' : '🌐'
  return <span className="text-[11px] leading-none">{flag}</span>
}

const PTAX = 5.12 // fallback if no fx_rate available

// ── Type label mappings (prototype-faithful) ─────────────────────────────────

const TYPE_MOVEMENT_PALETTE: Record<string, string> = {
  BUY: 'bg-blue-500/15 text-blue-500 dark:text-blue-400',
  SELL: 'bg-red-500/15 text-red-500 dark:text-red-400',
  BONUS: 'bg-emerald-500/15 text-emerald-500 dark:text-emerald-400',
  SUBSCRIPTION: 'bg-violet-500/15 text-violet-500 dark:text-violet-400',
  COME_COTAS: 'bg-amber-500/15 text-amber-500 dark:text-amber-400',
  FULL_REDEMPTION: 'bg-teal-500/15 text-teal-500 dark:text-teal-400',
  SELL_OPEN: 'bg-purple-500/15 text-purple-500 dark:text-purple-400',
  BUY_TO_OPEN: 'bg-purple-500/15 text-purple-500 dark:text-purple-400',
  BUY_TO_CLOSE: 'bg-purple-500/15 text-purple-500 dark:text-purple-400',
  SELL_TO_CLOSE: 'bg-purple-500/15 text-purple-500 dark:text-purple-400',
  EXERCISED: 'bg-amber-500/15 text-amber-500 dark:text-amber-400',
  EXPIRED: 'bg-gray-500/15 text-gray-500 dark:text-gray-400',
}

const TYPE_DISTRIBUTION_PALETTE: Record<string, string> = {
  DIVIDEND: 'bg-amber-500/15 text-amber-500 dark:text-amber-400',
  INTEREST: 'bg-cyan-500/15 text-cyan-500 dark:text-cyan-400',
  JCP: 'bg-emerald-500/15 text-emerald-500 dark:text-emerald-400',
  SECURITIES_LENDING: 'bg-orange-500/15 text-orange-500 dark:text-orange-400',
}

// ── Page ─────────────────────────────────────────────────────────────────────

export default function AssetDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [me, setMe] = useState<UserOut | null>(null)
  const [asset, setAsset] = useState<AssetOut | null>(null)
  const [fi, setFi] = useState<FinancialInstitutionOut | null>(null)
  const [account, setAccount] = useState<AccountOut | null>(null)
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
        const fis = await api.listFinancialInstitutions().catch(() => [])
        const acc = await api.getAccount(a.account_id).catch(() => null)
        if (acc) {
          setAccount(acc)
          setFi(fis.find(f => f.id === acc.financial_institution_id) ?? null)
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
        setMovements([...movs].sort((a, b) => b.event_date.localeCompare(a.event_date)))
        setDistributions([...dists].sort((a, b) => b.event_date.localeCompare(a.event_date)))
      })
      .catch(e => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false))
  }, [me, id])

  const distSumBRL = useMemo(
    () => distributions.reduce((s, d) => s + d.net_amount * (d.fx_rate || 1), 0),
    [distributions],
  )

  // Pseudo price evolution — 24 months, interpolated avg → current. Same
  // formula as the prototype (line 3294–3298).
  const priceSeries = useMemo(() => {
    const avg = position?.average_cost ?? 0
    const price = position?.current_price ?? asset?.current_price ?? 0
    const cur = Number(price)
    const a = Number(avg)
    if (!a || !cur) return []
    return Array.from({ length: 24 }, (_, i) => {
      const t = i / 23
      return a + (cur - a) * (0.3 + 0.7 * t) + Math.sin(i * 0.7) * (cur - a) * 0.08
    })
  }, [position, asset])

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

  // Derived values
  const qty = Number(position?.quantity_held ?? 0)
  const avg = position?.average_cost != null ? Number(position.average_cost) : null
  const price = (position?.current_price ?? asset.current_price) != null
    ? Number(position?.current_price ?? asset.current_price)
    : null
  const value = price != null && qty ? price * qty : null
  const cost = avg != null && qty ? avg * qty : null
  const pl = value != null && cost != null ? value - cost : null
  const valueBRL = position?.current_value_brl != null ? Number(position.current_value_brl) : null
  const costBRL = position?.total_invested_brl != null ? Number(position.total_invested_brl) : null
  const variation = position?.variation != null ? Number(position.variation) : null
  const rentabilidade = position?.rentabilidade != null ? Number(position.rentabilidade) : null
  const yoc = (costBRL && costBRL > 0) ? distSumBRL / costBRL : null
  const dy = (valueBRL && valueBRL > 0) ? distSumBRL / valueBRL : null
  const lastMovementDate = movements[0]?.event_date

  return (
    <AppLayout user={me}>
      <div className="space-y-6">
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
                <CountryFlag country={asset.country} />
                <ClassBadge klass={klass} size="xs" withDot={false} />
                <CcyPill ccy={ccy} />
                {!asset.is_active && (
                  <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium uppercase tracking-wider bg-gray-200 dark:bg-gray-800 text-gray-500">
                    Zerado
                  </span>
                )}
              </div>
              <div className="text-sm text-gray-500 mt-1">{asset.name}</div>
              {fi && account && (
                <div className="mt-2 flex items-center gap-2 text-[12px] text-gray-500">
                  <FILogo slug={fi.logo_slug} shortName={fi.short_name} size="sm" />
                  <span className="hover:text-gray-700 dark:hover:text-gray-300">{fi.long_name}</span>
                  <span>·</span>
                  <span className="hover:text-gray-700 dark:hover:text-gray-300">{account.name}</span>
                </div>
              )}
            </div>
            <div className="flex items-center gap-2 shrink-0">
              <button className="h-8 px-3 inline-flex items-center gap-1.5 rounded-lg text-[12px] bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700 transition-colors">
                <Settings className="w-3.5 h-3.5" /> Editar
              </button>
              <button className="h-8 px-3 inline-flex items-center gap-1.5 rounded-lg text-[12px] bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700 transition-colors">
                <Coins className="w-3.5 h-3.5" /> + Provento
              </button>
              <button className="h-8 px-3 inline-flex items-center gap-1.5 rounded-lg text-[12px] bg-indigo-500 hover:bg-indigo-400 text-white transition-colors">
                <Plus className="w-3.5 h-3.5" /> Lançamento
              </button>
              {asset.asset_class !== 'OPTION' && (
                <button
                  onClick={() => setOptionModalOpen(true)}
                  className="h-8 px-3 inline-flex items-center gap-1.5 rounded-lg text-[12px] bg-indigo-500 hover:bg-indigo-400 text-white transition-colors"
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
              value={fmtMoney(value, ccy, { compact: true })}
              sub={ccy === 'USD' && valueBRL != null
                ? fmtBRL(valueBRL, { compact: true })
                : `${fmtNum(qty, qty < 1 ? 4 : 0)} unidades`}
            />
            <KpiTile label="Preço médio" value={fmtMoney(avg, ccy)} />
            <KpiTile
              label="Preço atual"
              value={fmtMoney(price, ccy)}
              sub={asset.price_updated_at
                ? `atualizado · ${fmtRelDate(asset.price_updated_at)}${ccy === 'USD' && price != null ? ` · R$ ${(price * PTAX).toFixed(2)}` : ''}`
                : 'sem preço atual'}
            />
            <KpiTile
              label="P&L"
              value={fmtMoney(pl, ccy, { sign: true, compact: true })}
              sub={ccy === 'USD' && pl != null ? fmtBRL(pl * PTAX, { sign: true, compact: true }) : undefined}
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
              sub={fmtBRL(distSumBRL, { compact: true })}
              intent={yoc != null && yoc > 0 ? 'positive' : undefined}
            />
            <KpiTile label="DY" value={fmtPct(dy, 1)} sub="anualizado" />
          </div>
        </Card>

        {/* Price chart */}
        {priceSeries.length > 0 && (
          <Card>
            <SectionTitle action={
              <span className="text-[11px] text-gray-500">simulado · prototype</span>
            }>
              Preço · 24 meses
            </SectionTitle>
            <div className="overflow-hidden -mx-2">
              <Sparkline data={priceSeries} w={1200} h={180} color={klassColor} />
            </div>
            <div className="mt-3 flex items-center justify-between text-[10px] uppercase tracking-wider text-gray-500">
              <span>mai/24</span>
              <span>nov/24</span>
              <span>mai/25</span>
              <span>nov/25</span>
              <span className="text-indigo-500 dark:text-indigo-400">hoje</span>
            </div>
          </Card>
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
            <div className="text-[12px] text-gray-500 italic py-6 text-center">Sem lançamentos cadastrados.</div>
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
                    <th className="px-2"></th>
                  </tr>
                </thead>
                <tbody>
                  {movements.map(m => {
                    const typeCls = TYPE_MOVEMENT_PALETTE[m.type] || 'bg-gray-500/15 text-gray-500'
                    return (
                      <tr key={m.id} className="border-t border-gray-100 dark:border-gray-800 hover:bg-gray-50 dark:hover:bg-gray-800/30 transition-colors cursor-pointer">
                        <td className="px-2 py-2 tnum text-gray-400">{fmtDate(m.event_date)}</td>
                        <td className="px-2">
                          <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] uppercase tracking-wider ${typeCls}`}>
                            {m.type_label}
                          </span>
                        </td>
                        <td className="px-2 text-right tnum">
                          {m.quantity != null
                            ? (m.quantity < 1 ? m.quantity.toFixed(4) : fmtNum(m.quantity, m.quantity < 100 ? 2 : 0))
                            : '—'}
                        </td>
                        <td className="px-2 text-right tnum money text-gray-400">{m.unit_price != null ? fmtMoney(m.unit_price, m.currency) : '—'}</td>
                        <td className="px-2 text-right tnum money text-gray-500">{m.fee ? fmtMoney(m.fee, m.currency) : '—'}</td>
                        <td className="px-2 text-right">
                          <div className={`tnum money font-medium ${m.net_amount < 0 ? 'text-red-500 dark:text-red-400' : m.net_amount > 0 ? 'text-emerald-500 dark:text-emerald-400' : 'text-gray-500'}`}>
                            {fmtMoney(m.net_amount, m.currency, { sign: true })}
                          </div>
                          <CcyPill ccy={m.currency} />
                        </td>
                        <td className="px-2 text-gray-500"><MoreHorizontal className="w-4 h-4" /></td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </Card>

        {/* Proventos full table */}
        <Card>
          <SectionTitle action={
            <span className="text-[11px] tnum text-gray-500">
              Total <span className="money text-emerald-500 dark:text-emerald-400 font-medium">{fmtBRL(distSumBRL, { compact: true })}</span>
            </span>
          }>
            Proventos · {distributions.length}
          </SectionTitle>
          {distributions.length === 0 ? (
            <div className="text-[12px] text-gray-500 italic py-6 text-center">Sem proventos cadastrados.</div>
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
                    <th className="px-2"></th>
                  </tr>
                </thead>
                <tbody>
                  {distributions.map(d => {
                    const typeCls = TYPE_DISTRIBUTION_PALETTE[d.type] || 'bg-gray-500/15 text-gray-500'
                    return (
                      <tr key={d.id} className="border-t border-gray-100 dark:border-gray-800 hover:bg-gray-50 dark:hover:bg-gray-800/30 transition-colors cursor-pointer">
                        <td className="px-2 py-2 tnum text-gray-400">{fmtDate(d.event_date)}</td>
                        <td className="px-2">
                          <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] uppercase tracking-wider ${typeCls}`}>
                            {d.type_label}
                          </span>
                        </td>
                        <td className="px-2 text-right tnum money text-gray-400">{fmtMoney(d.gross_amount, d.currency)}</td>
                        <td className="px-2 text-right tnum money text-amber-500 dark:text-amber-400">{d.tax && d.tax > 0 ? '−' + fmtMoney(d.tax, d.currency) : '—'}</td>
                        <td className="px-2 text-right">
                          <div className="tnum money font-medium text-emerald-500 dark:text-emerald-400">{fmtMoney(d.net_amount, d.currency, { sign: true })}</div>
                          <CcyPill ccy={d.currency} />
                        </td>
                        <td className="px-2 text-gray-500"><MoreHorizontal className="w-4 h-4" /></td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </Card>

        {/* Open options card */}
        {asset.asset_class !== 'OPTION' && (
          <OpenOptionsCard
            key={optionsRefresh}
            underlyingId={asset.id}
            underlyingTicker={asset.ticker || asset.name}
            onAction={() => setOptionsRefresh(n => n + 1)}
            onAddOption={() => setOptionModalOpen(true)}
          />
        )}

        {/* Detalhes / metadata */}
        <Card>
          <SectionTitle>Detalhes</SectionTitle>
          <dl className="grid grid-cols-2 lg:grid-cols-4 gap-x-6 gap-y-3 text-[12px]">
            <Detail label="Ticker" value={asset.ticker || '—'} mono />
            <Detail label="CNPJ" value={asset.cnpj || '—'} mono />
            <Detail label="Classe">
              <ClassBadge klass={klass} size="xs" withDot={false} />
            </Detail>
            <Detail label="País">
              <span className="inline-flex items-center gap-1.5">
                <CountryFlag country={asset.country} />
                <span>{asset.country === 'BR' ? 'Brasil' : asset.country === 'US' ? 'EUA' : asset.country}</span>
              </span>
            </Detail>
            <Detail label="Moeda">
              <CcyPill ccy={ccy} />
            </Detail>
            <Detail label="Custodiante" value={fi?.short_name || '—'} />
            <Detail label="Conta" value={account?.name || '—'} />
            <Detail label="Status">
              {asset.is_active
                ? <span className="text-emerald-500 dark:text-emerald-400">Ativo</span>
                : <span className="text-gray-500">Zerado</span>}
            </Detail>
            <Detail label="Total investido" value={fmtBRL(costBRL, { compact: true })} tnum money />
            <Detail label="Total recebido" value={fmtBRL(distSumBRL, { compact: true })} tnum money tone="positive" />
            <Detail label="Lançamentos" value={String(movements.length)} tnum />
            <Detail label="Último lançamento" value={lastMovementDate ? fmtDate(lastMovementDate) : '—'} tnum />
          </dl>
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
  const intentColor =
    intent === 'negative' ? 'text-red-500 dark:text-red-400'
    : intent === 'positive' ? 'text-emerald-500 dark:text-emerald-400'
    : ''
  return (
    <div className="px-4 py-3 rounded-xl bg-gray-50 dark:bg-gray-800/40 border border-gray-200 dark:border-gray-800">
      <div className="text-[11px] uppercase tracking-wider font-medium text-gray-500 dark:text-gray-400">{label}</div>
      <div className={`mt-1 text-lg font-semibold tnum money flex items-center gap-2 ${intentColor}`}>
        {value}
      </div>
      {sub && <div className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">{sub}</div>}
    </div>
  )
}

function Detail({
  label, value, children, mono, tnum, money, tone,
}: {
  label: string
  value?: string
  children?: React.ReactNode
  mono?: boolean
  tnum?: boolean
  money?: boolean
  tone?: 'positive' | 'negative'
}) {
  const toneCls = tone === 'positive' ? 'text-emerald-500 dark:text-emerald-400'
    : tone === 'negative' ? 'text-red-500 dark:text-red-400'
    : 'text-gray-900 dark:text-white'
  const cls = `mt-0.5 ${mono ? 'font-mono' : ''} ${tnum ? 'tnum' : ''} ${money ? 'money' : ''} ${toneCls}`.trim()
  return (
    <div>
      <dt className="text-[10px] uppercase tracking-wider text-gray-500 dark:text-gray-400">{label}</dt>
      <dd className={cls}>{children ?? value}</dd>
    </div>
  )
}
