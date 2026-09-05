/* Spec 81 — aba "Fechamentos & rentabilidade": tiles de retorno acumulado
 * (12m, no ano, desde o início), gráfico do acumulado, evolução do valor
 * (sparkline com aportes, spec 50) e a tabela de resultado por fechamento. */
import { useMemo } from 'react'

import type {
  AssetMovementOut, AssetPerformanceOut, AssetSnapshotHistoryOut,
} from '../../lib/api'
import { fmtPct } from '../../lib/format'
import { fmtBRL, fmtMoney } from '../../lib/money'
import AssetSnapshotsCard from '../AssetSnapshotsCard'
import KpiTile from '../KpiTile'
import { Card, SectionTitle } from '../ui'
import AssetPerformanceTable from './AssetPerformanceTable'
import AssetReturnChart from './AssetReturnChart'

interface Props {
  assetId: string
  snapshotHistory: AssetSnapshotHistoryOut | null
  snapshotHistoryLoading: boolean
  movements: AssetMovementOut[]
  performance: AssetPerformanceOut | null
  performanceLoading: boolean
  performanceError: string | null
}

function intentOf(v: number | null | undefined): 'positive' | 'negative' | undefined {
  if (v == null) return undefined
  return v >= 0 ? 'positive' : 'negative'
}

export default function AssetPerformanceTab({
  assetId, snapshotHistory, snapshotHistoryLoading, movements,
  performance, performanceLoading, performanceError,
}: Props) {
  const ascRows = useMemo(() => performance ? [...performance.items].reverse() : [], [performance])
  const s = performance?.summary
  const ccy = performance?.currency ?? 'BRL'
  const isUsd = ccy !== 'BRL'

  return (
    <div className="space-y-6" data-testid="asset-tab-panel-performance">
      {performanceLoading && !performance && (
        <Card padding="p-5">
          <SectionTitle>Rentabilidade</SectionTitle>
          <div className="text-[12px] text-gray-400 py-4 text-center">Carregando…</div>
        </Card>
      )}

      {performanceError && !performance && (
        <Card padding="p-5">
          <SectionTitle>Rentabilidade</SectionTitle>
          <div className="text-[12px] text-red-500 py-4 text-center" data-testid="asset-performance-error">
            Não consegui calcular a rentabilidade: {performanceError}
          </div>
        </Card>
      )}

      {performance && s && (
        <>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3" data-testid="asset-performance-tiles">
            <KpiTile
              label="12 meses"
              value={fmtPct(s.return_12m_pct, 1, true)}
              intent={intentOf(s.return_12m_pct)}
              sub={s.return_12m_pct == null
                ? (s.months_in_12m < 12 ? `${s.months_in_12m} de 12 fechamentos` : 'mês sem retorno na janela')
                : isUsd ? `${fmtPct(s.return_12m_brl_pct, 1, true)} em BRL` : 'preço + proventos'}
            />
            <KpiTile
              label="No ano"
              value={fmtPct(s.return_ytd_pct, 1, true)}
              intent={intentOf(s.return_ytd_pct)}
              sub={s.return_ytd_pct == null
                ? `${s.months_in_ytd} fechamento${s.months_in_ytd === 1 ? '' : 's'} · sem retorno em algum mês`
                : isUsd ? `${fmtPct(s.return_ytd_brl_pct, 1, true)} em BRL` : `${s.months_in_ytd} fechamentos`}
            />
            <KpiTile
              label="Desde o início"
              value={fmtPct(s.since_inception_pct, 1, true)}
              intent={intentOf(s.since_inception_pct)}
              sub={s.since_inception_pct == null
                ? 'algum mês sem retorno'
                : isUsd ? `${fmtPct(s.since_inception_brl_pct, 1, true)} em BRL` : `${performance.items.length} fechamentos`}
            />
            <KpiTile
              label="Proventos · 12m"
              value={fmtMoney(Number(s.income_12m_native), ccy, { compact: true })}
              intent={Number(s.income_12m_native) > 0 ? 'positive' : undefined}
              sub={isUsd ? fmtBRL(Number(s.income_12m_brl), { compact: true }) : 'dividendos, JCP, aluguel, prêmios'}
            />
          </div>

          <AssetReturnChart rows={ascRows} />
        </>
      )}

      <AssetSnapshotsCard
        history={snapshotHistory}
        loading={snapshotHistoryLoading}
        assetId={assetId}
        movements={movements}
        hideTable={!performanceError}
        title="Valor da posição · fechamentos"
      />

      {performance && (
        <AssetPerformanceTable
          rows={performance.items}
          currency={performance.currency}
          isValueMode={performance.is_value_mode}
          assetId={assetId}
        />
      )}
    </div>
  )
}
