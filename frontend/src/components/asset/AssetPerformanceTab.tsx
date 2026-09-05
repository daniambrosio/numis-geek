/* Spec 81 — aba "Fechamentos & rentabilidade". Fase 3: só a tabela de
 * fechamentos (spec 50). Fase 5 adiciona tiles, gráfico acumulado e a
 * tabela de retorno mês a mês. */
import type { AssetMovementOut, AssetSnapshotHistoryOut } from '../../lib/api'
import AssetSnapshotsCard from '../AssetSnapshotsCard'

interface Props {
  assetId: string
  snapshotHistory: AssetSnapshotHistoryOut | null
  snapshotHistoryLoading: boolean
  movements: AssetMovementOut[]
}

export default function AssetPerformanceTab({
  assetId, snapshotHistory, snapshotHistoryLoading, movements,
}: Props) {
  return (
    <div className="space-y-6" data-testid="asset-tab-panel-performance">
      <AssetSnapshotsCard
        history={snapshotHistory}
        loading={snapshotHistoryLoading}
        assetId={assetId}
        movements={movements}
      />
    </div>
  )
}
