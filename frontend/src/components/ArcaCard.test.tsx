/* Spec 85 — card ARCA. */
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'

import ArcaCard from './ArcaCard'
import { parseAmount } from '../lib/arca'
import { api, type ArcaLetterOut, type ArcaSummaryOut } from '../lib/api'

function letter(key: ArcaLetterOut['key'], pct: number, extra: Partial<ArcaLetterOut> = {}): ArcaLetterOut {
  return {
    key, value_brl: String(pct * 1000), current_pct: pct, target_pct: '0.25',
    min_pct: '0.10', max_pct: '0.40', gap_brl: '0', status: 'IN_BAND',
    income_12m_brl: '0', yield_12m: null, income_share: 0, income_forward_brl: '0',
    unclassified_sub_value_brl: '0', subcategories: [], ...extra,
  }
}

const summary: ArcaSummaryOut = {
  as_of: '2026-10-31', total_brl: '1000', out_of_scope_brl: '0',
  unmapped_brl: '50', unmapped_count: 2, income_12m_total_brl: '80',
  attack_pct: 0.1, defense_pct: 0.3, unknown_role_pct: 0.6, targets_configured: true,
  letters: [
    letter('EQUITY_BR', 0.45, { status: 'ABOVE_BAND' }),
    letter('REAL_ESTATE', 0.2),
    letter('CASH', 0.3, {
      subcategories: [{
        key: 'CASH_POST_FIXED', role: 'DEFENSE', value_brl: '300', pct_of_letter: 1,
        pct_of_total: 0.3, target_pct_of_letter: '0.3333', target_pct_of_total: '0.0833',
        gap_brl: '-216.70', income_12m_brl: '0', yield_12m: 0,
      }],
    }),
    letter('GLOBAL', 0.05, { status: 'BELOW_BAND' }),
  ],
  assets: [],
}

beforeEach(() => vi.restoreAllMocks())

describe('ArcaCard', () => {
  it('renders letters, status and unmapped warning', () => {
    render(<ArcaCard workspaceId="ws1" summary={summary} />)
    expect(screen.getByText('Ações')).toBeInTheDocument()
    expect(screen.getByText('Acima da faixa')).toBeInTheDocument()
    expect(screen.getByText('Abaixo da faixa')).toBeInTheDocument()
    expect(screen.getByTestId('arca-unmapped').textContent).toMatch(/2 ativo/)
    expect(screen.getByTestId('arca-attack').textContent).toBe('10,0%')
  })

  it('expands a letter to show subcategories', () => {
    render(<ArcaCard workspaceId="ws1" summary={summary} />)
    expect(screen.queryByTestId('arca-sub-CASH_POST_FIXED')).toBeNull()
    fireEvent.click(screen.getByTestId('arca-letter-CASH'))
    expect(screen.getByTestId('arca-sub-CASH_POST_FIXED').textContent).toMatch(/Pós-fixado/)
  })

  it('simulates a contribution', async () => {
    const spy = vi.spyOn(api, 'arcaContributionPlan').mockResolvedValue({
      amount_brl: '1000', total_after_brl: '2000',
      letters: [{
        key: 'GLOBAL', current_brl: '50', amount_brl: '1000.00', after_brl: '1050',
        after_pct: 0.525, target_pct: '0.25', sell_suggestion_brl: '0', subcategories: [],
      }],
    })
    render(<ArcaCard workspaceId="ws1" summary={summary} />)
    fireEvent.change(screen.getByTestId('arca-amount'), { target: { value: '1.000' } })
    fireEvent.click(screen.getByTestId('arca-simulate'))
    await waitFor(() => expect(spy).toHaveBeenCalledWith('ws1', '1000'))
    expect(await screen.findByTestId('arca-plan')).toBeInTheDocument()
  })

  it('parses pt-BR amounts', () => {
    expect(parseAmount('R$ 10.000')).toBe(10000)
    expect(parseAmount('1.000')).toBe(1000)
    expect(parseAmount('1.234,56')).toBe(1234.56)
    expect(parseAmount('2500,5')).toBe(2500.5)
    expect(parseAmount('')).toBeNull()
  })

  it('rejects empty amount without calling the api', () => {
    const spy = vi.spyOn(api, 'arcaContributionPlan')
    render(<ArcaCard workspaceId="ws1" summary={summary} />)
    fireEvent.click(screen.getByTestId('arca-simulate'))
    expect(spy).not.toHaveBeenCalled()
    expect(screen.getByText(/maior que zero/)).toBeInTheDocument()
  })
})
