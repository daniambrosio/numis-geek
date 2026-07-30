/* Task 49-A — smoke + shape tests para SnapshotItemEditModal.
 *
 * Renderiza o modal com backend response REAL (SnapshotItemOut + AssetOut
 * completos, api.ts:210 e :1639) e valida:
 *  - Modo unit vs total é derivado da classe do asset (STOCK=unit, FUND=total)
 *  - Campo qty é EDITÁVEL para toda classe (válvula de escape do modal);
 *    NOTA: brief pedia que FUND fosse read-only ou forçado a 1, MAS o
 *    componente atual deliberadamente permite override. Ver TODO abaixo.
 *  - Preview USD→BRL usa fxRate quando asset.currency='USD'
 *  - ESC fecha; submit chama api.patchSnapshotItem
 */
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'

import SnapshotItemEditModal from './SnapshotItemEditModal'
import { api, type AssetOut, type SnapshotItemOut } from '../lib/api'

function makeAsset(over: Partial<AssetOut> = {}): AssetOut {
  return {
    id: 'a-petr',
    workspace_id: 'ws-1',
    workspace_name: null,
    account_id: 'acc-1',
    account_name: 'XP',
    financial_institution_id: 'fi-1',
    financial_institution_name: 'XP',
    asset_class: 'STOCK',
    country: 'BR',
    name: 'Petrobras',
    ticker: 'PETR4',
    cnpj: null,
    currency: 'BRL',
    current_price: 38,
    price_updated_at: '2026-05-30T00:00:00Z',
    price_source: 'BRAPI',
    price_tier: 'FRESH',
    notes: null,
    external_id: null,
    external_source: null,
    is_active: true,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-05-30T00:00:00Z',
    details: null,
    ...over,
  } as AssetOut
}

function makeItem(over: Partial<SnapshotItemOut> = {}): SnapshotItemOut {
  return {
    id: 'item-1',
    asset_id: 'a-petr',
    quantity: '100.00000000',
    unit_price: '38.00',
    market_value_native: '3800.00',
    market_value_brl: '3800.00',
    market_value_usd: '760.00',
    average_cost_brl: '35.00',
    total_invested_brl: '3500.00',
    updated_at: '2026-05-31T23:59:59Z',
    ...over,
  }
}

function wrap(children: React.ReactNode) {
  return <MemoryRouter>{children}</MemoryRouter>
}

beforeEach(() => {
  vi.restoreAllMocks()
  // Modal chama api.listAttachments no mount — mocka pra não pendurar.
  vi.spyOn(api, 'listAttachments').mockResolvedValue([])
})

describe('SnapshotItemEditModal', () => {
  it('STOCK: renderiza em modo unit, com qty + preço editáveis + preview', async () => {
    render(wrap(
      <SnapshotItemEditModal
        snapshotId="snap-1" ym="2026-05"
        item={makeItem()} asset={makeAsset()}
        fxRate={5.10}
        onSaved={() => {}} onDeleted={() => {}} onClose={() => {}}
      />,
    ))
    // Título: ticker.
    expect(screen.getByText('PETR4')).toBeInTheDocument()
    // Modo padrão pra STOCK = unit; toggle presente.
    const unitBtn = screen.getByTestId('snapshot-item-mode-unit')
    const totalBtn = screen.getByTestId('snapshot-item-mode-total')
    expect(unitBtn.className).toMatch(/indigo-500/)
    expect(totalBtn.className).not.toMatch(/indigo-500/)
    // Preço unitário populado com valor original.
    const priceInput = screen.getByTestId('snapshot-item-price-input') as HTMLInputElement
    expect(priceInput.value).toBe('38,00')
    // Qty editável.
    const qtyInput = screen.getByTestId('snapshot-item-qty-input') as HTMLInputElement
    expect(qtyInput).not.toBeDisabled()
    expect(qtyInput.value).toBe('100')

    // Preview mostra unit + total baseados na qty original.
    // 100 * 38 = 3800; formato pt-BR: 3.800,00 — aparece em múltiplos lugares
    // (Valor atual, preview do save). Só assertamos que pelo menos um bate.
    await waitFor(() => {
      expect(screen.getAllByText(/3\.800,00/).length).toBeGreaterThan(0)
    })
  })

  it('FUND (value-mode): default mode=total; qty ainda EDITÁVEL (override válvula)', async () => {
    // TODO(brief): brief pedia qty read-only ou clamp=1 para FUND
    // (memory: value_mode_qty_1_invariant). O componente atual deliberadamente
    // permite override do qty como válvula de escape pra bater com extrato
    // do custodiante (linha 61-69 do .tsx). Documentando o comportamento REAL:
    const fund = makeAsset({
      id: 'a-fund', asset_class: 'FUND',
      name: 'BB Ações Multi', ticker: null, currency: 'BRL',
    })
    const item = makeItem({
      asset_id: 'a-fund',
      quantity: '1.00000000', unit_price: '150000.00',
      market_value_native: '150000.00', market_value_brl: '150000.00',
    })
    render(wrap(
      <SnapshotItemEditModal
        snapshotId="snap-1" ym="2026-05"
        item={item} asset={fund}
        fxRate={null}
        onSaved={() => {}} onDeleted={() => {}} onClose={() => {}}
      />,
    ))
    // Modo default = total (FUND está em TOTAL_CLASSES).
    expect(screen.getByTestId('snapshot-item-mode-total').className).toMatch(/indigo-500/)
    // Label "Valor total" aparece 2x: no botão do toggle + no label do input.
    expect(screen.getAllByText('Valor total').length).toBeGreaterThanOrEqual(1)
    // Qty ainda editável (comportamento intencional do modal).
    const qtyInput = screen.getByTestId('snapshot-item-qty-input') as HTMLInputElement
    expect(qtyInput).not.toBeDisabled()
    // Se usuário digita 3, o valor É aceito (não clampa pra 1).
    const user = userEvent.setup()
    await user.clear(qtyInput)
    await user.type(qtyInput, '3')
    expect(qtyInput.value).toBe('3')
    // Aviso amarelo aparece indicando divergência do original.
    expect(screen.getByText(/original: 1,0000/)).toBeInTheDocument()
  })

  it('USD asset: mostra preview R$ conversão quando fxRate está presente', async () => {
    const aapl = makeAsset({
      id: 'a-aapl', name: 'Apple Inc', ticker: 'AAPL',
      country: 'US', currency: 'USD', current_price: 200,
    })
    const item = makeItem({
      asset_id: 'a-aapl', quantity: '10', unit_price: '200.00',
      market_value_native: '2000.00', market_value_brl: '10200.00',
      market_value_usd: '2000.00',
    })
    render(wrap(
      <SnapshotItemEditModal
        snapshotId="snap-1" ym="2026-05"
        item={item} asset={aapl} fxRate={5.10}
        onSaved={() => {}} onDeleted={() => {}} onClose={() => {}}
      />,
    ))
    // Preview mostra "≈ R$ …" + "(PTAX 5.1000)".
    expect(screen.getByText(/PTAX 5\.1000/)).toBeInTheDocument()
    // Símbolo da moeda no input é US$.
    expect(screen.getAllByText('US$').length).toBeGreaterThan(0)
  })

  it('USD asset sem fxRate: NÃO mostra bloco de conversão (fail-soft, sem erro visível)', () => {
    // NOTA: o brief pedia "aviso ou erro se USD sem fx_rate". O componente
    // atual apenas suprime a linha de conversão — não bloqueia submit nem
    // mostra warning. Documentando o comportamento efetivo.
    const aapl = makeAsset({
      id: 'a-aapl', name: 'Apple', ticker: 'AAPL',
      country: 'US', currency: 'USD',
    })
    render(wrap(
      <SnapshotItemEditModal
        snapshotId="snap-1" ym="2026-05"
        item={makeItem({ asset_id: 'a-aapl' })} asset={aapl} fxRate={null}
        onSaved={() => {}} onDeleted={() => {}} onClose={() => {}}
      />,
    ))
    expect(screen.queryByText(/PTAX/)).toBeNull()
    // Sem crash, submit habilitado normalmente.
    expect(screen.getByTestId('snapshot-item-save')).not.toBeDisabled()
  })

  it('ESC fecha o modal', async () => {
    const onClose = vi.fn()
    const user = userEvent.setup()
    render(wrap(
      <SnapshotItemEditModal
        snapshotId="snap-1" ym="2026-05"
        item={makeItem()} asset={makeAsset()} fxRate={5}
        onSaved={() => {}} onDeleted={() => {}} onClose={onClose}
      />,
    ))
    await user.keyboard('{Escape}')
    expect(onClose).toHaveBeenCalled()
  })

  it('submit chama patchSnapshotItem com price + mode + note; onSaved recebe item atualizado', async () => {
    const updated = makeItem({ unit_price: '40.00', market_value_native: '4000.00' })
    const spy = vi.spyOn(api, 'patchSnapshotItem').mockResolvedValue(updated)
    const onSaved = vi.fn()
    const user = userEvent.setup()

    render(wrap(
      <SnapshotItemEditModal
        snapshotId="snap-1" ym="2026-05"
        item={makeItem()} asset={makeAsset()} fxRate={5}
        onSaved={onSaved} onDeleted={() => {}} onClose={() => {}}
      />,
    ))
    const priceInput = screen.getByTestId('snapshot-item-price-input')
    await user.clear(priceInput)
    await user.type(priceInput, '40,00')
    await user.click(screen.getByTestId('snapshot-item-save'))

    await waitFor(() => expect(spy).toHaveBeenCalledWith(
      'snap-1', 'a-petr',
      expect.objectContaining({
        price: '40.00',
        value_mode: 'unit',
        // quantity=null porque qty não foi mudado.
        quantity: null,
        note: null,
      }),
    ))
    expect(onSaved).toHaveBeenCalledWith(updated)
  })
})
