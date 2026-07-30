/* Task 48-B — smoke + shape tests para AffectedSnapshotsModal.
 *
 * Renderiza o modal com response REAL do endpoint
 * POST /snapshots/affected-snapshots (shape completo) e valida:
 *  - listagem: cada snapshot afetado aparece com período + Valor total
 *  - ESC fecha (memory: useEscapeKey obrigatório)
 *  - clique em "Atualizar fechamento" chama recomputeSnapshotItem + onApplied
 *  - clique em "Não atualizar fechamento" abre fase skipReason;
 *    confirmar chama skipRecomputeSnapshotItem + onSkipped
 */
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import AffectedSnapshotsModal from './AffectedSnapshotsModal'
import { api, type AffectedSnapshotOut, type SnapshotItemOut } from '../lib/api'

function makeAffected(over: Partial<AffectedSnapshotOut> = {}): AffectedSnapshotOut {
  // Shape completo copiado de AffectedSnapshotOut (api.ts:519).
  return {
    snapshot_id: 'snap-1',
    period_end_date: '2026-05-31',
    ym: '2026-05',
    status: 'IN_REVIEW',
    has_item: true,
    old_quantity: '100.00000000',
    new_quantity: '200.00000000',
    old_market_value_brl: '3800.00',
    new_market_value_brl: '7600.00',
    old_total_invested_brl: '3800.00',
    new_total_invested_brl: '7600.00',
    snapshot_total_value_brl: '13100000.00',
    ...over,
  }
}

function makeItem(): SnapshotItemOut {
  return {
    id: 'item-1', asset_id: 'a-petr',
    quantity: '200', unit_price: '38.00',
    market_value_native: '7600.00',
    market_value_brl: '7600.00',
    market_value_usd: '1500.00',
    average_cost_brl: '38.00',
    total_invested_brl: '7600.00',
    updated_at: '2026-06-01T00:00:00Z',
  }
}

beforeEach(() => {
  vi.restoreAllMocks()
})

describe('AffectedSnapshotsModal', () => {
  it('renderiza N snapshots afetados com período + valores antes → depois', () => {
    const affected: AffectedSnapshotOut[] = [
      makeAffected(),
      makeAffected({
        snapshot_id: 'snap-2', ym: '2026-06',
        period_end_date: '2026-06-30', status: 'CLOSED',
        snapshot_total_value_brl: '13200000.00',
      }),
    ]
    render(
      <AffectedSnapshotsModal
        assetId="a-petr" assetLabel="PETR4"
        affected={affected}
        triggerEventType="asset_movement.create"
        triggerEventId="mov-42"
        onClose={() => {}}
        onApplied={() => {}}
        onSkipped={() => {}}
      />,
    )
    // Cabeçalho + contagem.
    expect(screen.getByText('Impacto em fechamentos')).toBeInTheDocument()
    expect(screen.getByText(/2 fechamentos/)).toBeInTheDocument()
    // Períodos em português (Mai/26, Jun/26) — aparecem tanto na tabela
    // quanto na linha "Patrimônio total se atualizar", então getAllByText.
    expect(screen.getAllByText('Mai/26').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('Jun/26').length).toBeGreaterThanOrEqual(1)
    // Snapshot CLOSED destacado — aparece 2x: no aviso do topo (strong) e no
    // badge de status da linha CLOSED.
    expect(screen.getAllByText(/CLOSED/).length).toBeGreaterThanOrEqual(1)
    // Aviso de reabertura automática (hasClosed).
    expect(screen.getByText(/serão reabertos automaticamente/)).toBeInTheDocument()
    // Delta de qty visível (linha "Qtd antes → depois").
    expect(screen.getByText('Qtd antes → depois')).toBeInTheDocument()
  })

  it('ESC fecha o modal (via useEscapeKey)', async () => {
    const onClose = vi.fn()
    const user = userEvent.setup()
    render(
      <AffectedSnapshotsModal
        assetId="a-petr" affected={[makeAffected()]}
        triggerEventType="asset_movement.create" triggerEventId="mov-1"
        onClose={onClose} onApplied={() => {}} onSkipped={() => {}}
      />,
    )
    await user.keyboard('{Escape}')
    expect(onClose).toHaveBeenCalled()
  })

  it('clicar "Atualizar" chama recomputeSnapshotItem + onApplied', async () => {
    const spy = vi.spyOn(api, 'recomputeSnapshotItem').mockResolvedValue(makeItem())
    const onApplied = vi.fn()
    const user = userEvent.setup()
    render(
      <AffectedSnapshotsModal
        assetId="a-petr" affected={[makeAffected()]}
        triggerEventType="asset_movement.create" triggerEventId="mov-1"
        onClose={() => {}} onApplied={onApplied} onSkipped={() => {}}
      />,
    )
    await user.click(screen.getByTestId('affected-snapshots-apply'))
    await waitFor(() => expect(spy).toHaveBeenCalledWith(
      'snap-1', 'a-petr',
      { trigger_event_type: 'asset_movement.create', trigger_event_id: 'mov-1' },
    ))
    expect(onApplied).toHaveBeenCalled()
  })

  it('"Não atualizar fechamento" abre fase skip, exige reason, e confirma chama skipRecomputeSnapshotItem', async () => {
    const spy = vi.spyOn(api, 'skipRecomputeSnapshotItem').mockResolvedValue(undefined as unknown as void)
    const onSkipped = vi.fn()
    const user = userEvent.setup()
    render(
      <AffectedSnapshotsModal
        assetId="a-petr" affected={[makeAffected()]}
        triggerEventType="asset_movement.create" triggerEventId="mov-1"
        onClose={() => {}} onApplied={() => {}} onSkipped={onSkipped}
      />,
    )

    // Abre fase skipReason.
    await user.click(screen.getByTestId('affected-snapshots-skip'))
    const reasonInput = screen.getByTestId('skip-reason-input')
    expect(reasonInput).toBeInTheDocument()

    // Confirmar desabilitado sem reason.
    const confirmBtn = screen.getByTestId('affected-snapshots-skip-confirm')
    expect(confirmBtn).toBeDisabled()

    // Preenche reason + confirma.
    await user.type(reasonInput, 'Fechamento já reportado ao IR')
    expect(confirmBtn).not.toBeDisabled()
    await user.click(confirmBtn)

    await waitFor(() => expect(spy).toHaveBeenCalledWith(
      'snap-1', 'a-petr',
      {
        trigger_event_type: 'asset_movement.create',
        trigger_event_id: 'mov-1',
        reason: 'Fechamento já reportado ao IR',
      },
    ))
    expect(onSkipped).toHaveBeenCalled()
  })

  it('múltiplos snapshots + toggleAll: descheck todos desabilita apply', async () => {
    const affected: AffectedSnapshotOut[] = [
      makeAffected(),
      makeAffected({ snapshot_id: 'snap-2', ym: '2026-06', period_end_date: '2026-06-30' }),
    ]
    const user = userEvent.setup()
    render(
      <AffectedSnapshotsModal
        assetId="a-petr" affected={affected}
        triggerEventType="asset_movement.create" triggerEventId="mov-1"
        onClose={() => {}} onApplied={() => {}} onSkipped={() => {}}
      />,
    )
    // Um checkbox por snapshot + o master.
    const checkMai = screen.getByTestId('affected-snapshot-check-2026-05') as HTMLInputElement
    const checkJun = screen.getByTestId('affected-snapshot-check-2026-06') as HTMLInputElement
    expect(checkMai.checked).toBe(true)
    expect(checkJun.checked).toBe(true)

    await user.click(checkMai)
    await user.click(checkJun)
    // Apply button desabilita quando selected.size = 0.
    expect(screen.getByTestId('affected-snapshots-apply')).toBeDisabled()
  })
})
