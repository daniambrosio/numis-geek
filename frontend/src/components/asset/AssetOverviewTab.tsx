/* Spec 81 — aba "Visão geral": contexto de opção (spec 34), gráfico de preço
 * (spec 46), valuation (spec 61b) e opções em aberto. */
import type {
  AssetOut, AssetPriceHistoryOut, AssetPriceHistoryPeriod, PositionOut, UserOut,
} from '../../lib/api'
import { fmtDate, fmtMonthYY } from '../../lib/format'
import OpenOptionsCard from '../OpenOptionsCard'
import OptionContextCard from '../OptionContextCard'
import Sparkline from '../Sparkline'
import ValuationCard from '../ValuationCard'
import { Card, GroupingToggle, SectionTitle } from '../ui'

const PERIOD_LABEL: Record<AssetPriceHistoryPeriod, string> = {
  '6m':  '6 meses',
  '12m': '12 meses',
  '24m': '24 meses',
  'all': 'tudo',
}

export function PriceChartAxis({ points }: { points: { date: string }[] }) {
  // Pick 4 evenly spaced anchors out of the series + "hoje" at the end.
  const n = points.length
  if (n < 2) return null
  const idxs = [0, Math.floor(n / 4), Math.floor(n / 2), Math.floor((3 * n) / 4)]
  const anchors = idxs.map(i => fmtMonthYY(points[i].date))
  return (
    <div className="mt-3 flex items-center justify-between text-[10px] uppercase tracking-wider text-gray-500">
      {anchors.map((a, i) => <span key={i}>{a}</span>)}
      <span className="text-indigo-500 dark:text-indigo-400">hoje</span>
    </div>
  )
}

interface Props {
  asset: AssetOut
  me: UserOut
  underlying: AssetOut | null
  position: PositionOut | null
  priceHistory: AssetPriceHistoryOut | null
  pricePeriod: AssetPriceHistoryPeriod
  onPricePeriodChange: (p: AssetPriceHistoryPeriod) => void
  klassColor: string
  optionsRefresh: number
  onOptionsAction: () => void
  onAddOption: () => void
}

export default function AssetOverviewTab({
  asset, me, underlying, position, priceHistory, pricePeriod, onPricePeriodChange,
  klassColor, optionsRefresh, onOptionsAction, onAddOption,
}: Props) {
  const priceSeries = priceHistory?.points.map(p => Number(p.unit_price)) ?? []
  return (
    <div className="space-y-6" data-testid="asset-tab-panel-overview">
      {asset.asset_class === 'OPTION' && underlying && (
        <OptionContextCard option={asset} underlying={underlying} position={position} />
      )}

      {priceSeries.length >= 2 && priceHistory && (
        <Card>
          <SectionTitle action={
            <div className="flex items-center gap-3">
              <span className="text-[11px] text-gray-500">
                {priceHistory.points.length} fechamentos · {priceHistory.currency}
              </span>
              <GroupingToggle
                value={pricePeriod}
                onChange={(v) => onPricePeriodChange(v as AssetPriceHistoryPeriod)}
                options={[
                  { id: '6m',  label: '6M'   },
                  { id: '12m', label: '12M'  },
                  { id: '24m', label: '24M'  },
                  { id: 'all', label: 'Tudo' },
                ]}
              />
            </div>
          }>
            Preço · {PERIOD_LABEL[pricePeriod]}
          </SectionTitle>
          <div className="overflow-hidden -mx-2">
            <Sparkline data={priceSeries} w={1200} h={180} color={klassColor} />
          </div>
          <PriceChartAxis points={priceHistory.points} />
          {(priceHistory.adjustments?.length ?? 0) > 0 && (
            <div className="mt-2 text-[10px] text-gray-500" data-testid="price-chart-adjustments">
              Série ajustada por{' '}
              {priceHistory.adjustments!.map((a, i) => {
                const r = Number(a.ratio)
                const label = a.event_type === 'SPLIT'
                  ? `desdobramento 1:${Number.isInteger(r) ? r : r.toFixed(2)}`
                  : `agrupamento ${Number.isInteger(1 / r) ? `${Math.round(1 / r)}:1` : `×${r}`}`
                return (
                  <span key={a.event_date}>
                    {i > 0 ? ' e ' : ''}{label} em {fmtDate(a.event_date)}
                  </span>
                )
              })}
              . A tabela de fechamentos mostra o preço bruto de cada mês.
            </div>
          )}
        </Card>
      )}

      <ValuationCard assetId={asset.id} canRefresh={me.role !== 'member'} />

      {asset.asset_class !== 'OPTION' && (
        <OpenOptionsCard
          key={optionsRefresh}
          underlyingId={asset.id}
          underlyingTicker={asset.ticker || asset.name}
          onAction={onOptionsAction}
          onAddOption={onAddOption}
        />
      )}
    </div>
  )
}
