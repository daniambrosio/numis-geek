/* Task 48-A — smoke + shape tests para SnapshotDriftPanel.
 *
 * IMPORTANTE: apesar do brief mencionar botões "Recompute" / "Skip", o
 * componente REAL (`SnapshotDriftPanel.tsx`) é apenas um painel de
 * exibição — lista das divergências que o usuário já *aceitou*
 * ("Manter divergência" no `AffectedSnapshotsModal`). Não há callbacks
 * de ação aqui, e o "empty state" retorna null (o painel some).
 * Os testes abaixo refletem o comportamento efetivo do componente.
 */
import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

import SnapshotDriftPanel from './SnapshotDriftPanel'
import type { DriftEntryOut } from '../lib/api'

function makeDrift(over: Partial<DriftEntryOut> = {}): DriftEntryOut {
  // Shape copiado do endpoint GET /snapshots/{id}/drift.
  return {
    asset_id: 'a-petr',
    asset_name: 'Petrobras',
    asset_ticker: 'PETR4',
    trigger_event_type: 'asset_movement.create',
    trigger_event_id: 'mov-123',
    reason: 'Lançamento retroativo de 2026-04-15 (BUY 100@38,00) — usuário optou por manter o snapshot Mai/26 congelado (já reportado ao IR).',
    user_email: 'daniel@example.com',
    created_at: '2026-06-01T14:32:00Z',
    ...over,
  }
}

function wrap(children: React.ReactNode) {
  return <MemoryRouter>{children}</MemoryRouter>
}

describe('SnapshotDriftPanel', () => {
  it('renderiza duas entradas com asset name/ticker e reason (retroactive movement)', () => {
    const drift: DriftEntryOut[] = [
      makeDrift(),
      makeDrift({
        asset_id: 'a-aapl',
        asset_name: 'Apple Inc',
        asset_ticker: 'AAPL',
        trigger_event_type: 'corporate_action.create',
        trigger_event_id: 'ca-456',
        reason: 'Split 4:1 retroativo — snapshot Mar/26 mantido no valor original.',
        user_email: 'daniel@example.com',
        created_at: '2026-06-02T09:10:00Z',
      }),
    ]
    render(wrap(<SnapshotDriftPanel drift={drift} />))

    // Header + badge de contagem.
    expect(screen.getByText('Divergências aceitas')).toBeInTheDocument()
    expect(screen.getByText(/2 entradas/)).toBeInTheDocument()

    // Cada entrada renderiza ticker + reason + trigger label.
    expect(screen.getByText('PETR4')).toBeInTheDocument()
    expect(screen.getByText('AAPL')).toBeInTheDocument()
    expect(screen.getByText(/Lançamento retroativo de 2026-04-15/)).toBeInTheDocument()
    expect(screen.getByText(/Split 4:1 retroativo/)).toBeInTheDocument()
    expect(screen.getByText('Lançamento criado')).toBeInTheDocument()
    expect(screen.getByText('Corporate action')).toBeInTheDocument()
    // Attribution.
    expect(screen.getAllByText(/daniel@example\.com/i).length).toBeGreaterThan(0)
  })

  it('drift=[] → não renderiza o painel (empty state = null)', () => {
    // O componente real retorna `null` quando drift está vazio; não há
    // "Nenhuma divergência" pra mostrar. Confirma que nada é renderizado.
    const { container } = render(wrap(<SnapshotDriftPanel drift={[]} />))
    expect(container.firstChild).toBeNull()
    expect(screen.queryByText('Divergências aceitas')).toBeNull()
  })

  it('entrada com asset_id=null (ativo removido) não crasha e mostra rótulo neutro', () => {
    // Backend pode devolver drift com asset_id=null se o asset foi
    // deactivated depois. Componente precisa lidar sem crash.
    const drift: DriftEntryOut[] = [
      makeDrift({
        // @ts-expect-error — asset_id no shape do backend pode vir null; o
        // TS diz string mas na prática o componente checa null.
        asset_id: null,
        asset_name: null,
        asset_ticker: null,
      }),
    ]
    render(wrap(<SnapshotDriftPanel drift={drift} />))
    expect(screen.getByText(/ativo removido/)).toBeInTheDocument()
  })

  it('singular: "1 entrada" (não "1 entradas")', () => {
    render(wrap(<SnapshotDriftPanel drift={[makeDrift()]} />))
    expect(screen.getByText('1 entrada')).toBeInTheDocument()
  })
})
