import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import OptionModal from './OptionModal'
import { api, type AssetOut, type OptionOut } from '../lib/api'

function makeStock(overrides: Partial<AssetOut> = {}): AssetOut {
  return {
    id: 'a-itub',
    workspace_id: 'ws-1',
    workspace_name: null,
    account_id: 'acc-1',
    account_name: 'XP',
    financial_institution_id: 'fi-1',
    financial_institution_name: 'XP',
    asset_class: 'STOCK',
    country: 'BR',
    name: 'Itau',
    ticker: 'ITUB4',
    cnpj: null,
    currency: 'BRL',
    current_price: 38.45,
    price_updated_at: null,
    price_source: null,
    price_tier: 'FRESH',
    notes: null,
    external_id: null,
    external_source: null,
    is_active: true,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    details: null,
    ...overrides,
  }
}

beforeEach(() => {
  vi.restoreAllMocks()
  vi.spyOn(api, 'parseOption').mockResolvedValue({
    prefix: 'ITUB', month: 6, option_type: 'PUT',
    strike_digits: '34', strike_suggested: 34, adjustment_suffix: null,
  })
})

describe('OptionModal standalone (Spec 36)', () => {
  it('renders the underlying picker when no underlying is passed', () => {
    render(
      <OptionModal
        candidates={[makeStock(), makeStock({ id: 'a-wege', ticker: 'WEGE3', asset_class: 'STOCK' })]}
        onClose={() => {}}
        onSaved={() => {}}
      />,
    )
    const picker = screen.getByTestId('option-underlying-picker') as HTMLSelectElement
    const labels = Array.from(picker.querySelectorAll('option')).map(o => o.textContent ?? '')
    expect(labels.join(' ')).toContain('ITUB4')
    expect(labels.join(' ')).toContain('WEGE3')
  })

  it('hides the picker when an underlying is pre-selected', () => {
    render(<OptionModal underlying={makeStock()} onClose={() => {}} onSaved={() => {}} />)
    expect(screen.queryByTestId('option-underlying-picker')).toBeNull()
  })

  it('filters out non-STOCK/REIT/ETF assets from the picker', () => {
    const fgts = makeStock({ id: 'a-fgts', ticker: null, name: 'FGTS Caixa', asset_class: 'FGTS' })
    const opt = makeStock({ id: 'a-opt', ticker: 'ITUBR364', asset_class: 'OPTION' })
    render(
      <OptionModal candidates={[makeStock(), fgts, opt]} onClose={() => {}} onSaved={() => {}} />,
    )
    const picker = screen.getByTestId('option-underlying-picker') as HTMLSelectElement
    const text = Array.from(picker.querySelectorAll('option')).map(o => o.textContent ?? '').join(' ')
    expect(text).not.toContain('FGTS')
    expect(text).not.toContain('ITUBR364')
  })

  it('"Salvar e abrir outra" keeps underlying and clears ticker/strike/qty', async () => {
    const created: OptionOut = {
      id: 'opt-1', ticker: 'ITUBR364', name: 'ITUB4 06 PUT 34',
      underlying_id: 'a-itub', underlying_ticker: 'ITUB4',
      option_type: 'PUT', strike_price: 34, expiration_date: '2026-06-20',
      contract_size: 100, currency: 'BRL', is_active: true,
      account_id: 'acc-1', workspace_id: 'ws-1',
    }
    const createSpy = vi.spyOn(api, 'createOption').mockResolvedValue(created)
    const onSaved = vi.fn()

    render(<OptionModal underlying={makeStock()} onClose={() => {}} onSaved={onSaved} />)

    await userEvent.type(screen.getByPlaceholderText('ITUBR364'), 'ITUBR364')
    // strike is auto-populated by the parser; quantity and price still needed
    await userEvent.type(screen.getByPlaceholderText('1000'), '1000')
    await userEvent.type(screen.getByPlaceholderText('0.09'), '0.10')
    const dateInputs = document.querySelectorAll('input[type="date"]')
    // [0] is Vencimento, [1] is operation Data
    await userEvent.type(dateInputs[0] as HTMLInputElement, '2026-06-20')

    await userEvent.click(screen.getByTestId('option-save-and-new'))

    expect(createSpy).toHaveBeenCalled()
    expect(onSaved).toHaveBeenCalledWith(created)
    // Ticker input reset; toast appears.
    expect((screen.getByPlaceholderText('ITUBR364') as HTMLInputElement).value).toBe('')
    expect(screen.getByTestId('option-toast')).toHaveTextContent('Opção ITUBR364 criada')
  })
})
