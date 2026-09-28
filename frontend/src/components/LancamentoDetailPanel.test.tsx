/* Drawer de lançamento — navegação pra página do ativo.
 *
 * O link "Abrir ativo" leva pra /assets/:id e carrega state.from pra que
 * a página do ativo mostre "Voltar pra Lançamentos".
 */
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'

import LancamentoDetailPanel from './LancamentoDetailPanel'
import { api, type AssetMovementOut, type AssetOut, type FinancialInstitutionOut } from '../lib/api'

const asset: AssetOut = {
  id: 'a1', workspace_id: 'ws1', workspace_name: 'Família',
  account_id: 'acc1', account_name: 'Avenue Inv',
  financial_institution_id: 'fi1', financial_institution_name: 'Avenue',
  asset_class: 'ETF', country: 'US',
  name: 'IB01 iShares $ Treasury Bond 0-1yr UCITS ETF', ticker: 'LON:IB01', cnpj: null,
  currency: 'USD',
  current_price: 121, price_updated_at: null,
  price_source: null, price_tier: null,
  notes: null, external_id: null, external_source: null,
  is_active: true, details: null,
  created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
}

const fi: FinancialInstitutionOut = {
  id: 'fi1', short_name: 'Avenue', long_name: 'Avenue Securities LLC',
  country: 'US', logo_slug: 'avenue', brand_color: null, has_logo: false, is_active: true,
  created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
}

const mov: AssetMovementOut = {
  id: 'm1', workspace_id: 'ws1', asset_id: 'a1',
  asset_name: asset.name, asset_ticker: asset.ticker,
  type: 'BUY', type_label: 'Compra',
  event_date: '2026-08-04', settlement_date: null,
  quantity: 100, unit_price: 121.36, gross_amount: 12136, fee: 30.34, tax: null,
  net_amount: 12166.34, currency: 'USD', fx_rate: 5.1047,
  notes: null, external_id: null, external_source: null, nota_negociacao_number: null,
  is_active: true, created_at: '2026-08-04T00:00:00Z', updated_at: '2026-08-04T00:00:00Z',
}

function AssetStub() {
  const loc = useLocation() as { state?: { from?: string; fromLabel?: string } }
  return <div data-testid="asset-page">{loc.state?.fromLabel ?? 'sem-state'}</div>
}

beforeEach(() => {
  vi.restoreAllMocks()
  vi.spyOn(api, 'listAttachments').mockResolvedValue([])
})

describe('LancamentoDetailPanel — abrir ativo', () => {
  it('navega pra /assets/:id com state.from apontando pra Lançamentos', async () => {
    render(
      <MemoryRouter initialEntries={['/asset-movements']}>
        <Routes>
          <Route
            path="/asset-movements"
            element={
              <LancamentoDetailPanel
                lancamento={mov} asset={asset} fi={fi}
                onClose={() => {}} onEdit={() => {}} onDeactivate={() => {}}
              />
            }
          />
          <Route path="/assets/:id" element={<AssetStub />} />
        </Routes>
      </MemoryRouter>,
    )
    const link = screen.getByTestId('lancamento-open-asset')
    expect(link).toHaveAttribute('href', '/assets/a1')
    fireEvent.click(link)
    await waitFor(() => expect(screen.getByTestId('asset-page')).toHaveTextContent('Lançamentos'))
  })

  it('não mostra o link quando o ativo ainda não carregou', () => {
    render(
      <MemoryRouter>
        <LancamentoDetailPanel
          lancamento={mov} asset={null} fi={null}
          onClose={() => {}} onEdit={() => {}} onDeactivate={() => {}}
        />
      </MemoryRouter>,
    )
    expect(screen.queryByTestId('lancamento-open-asset')).toBeNull()
  })
})
