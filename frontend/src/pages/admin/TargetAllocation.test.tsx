/* Spec 61a — Target Allocation page tests. */
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

import TargetAllocation from './TargetAllocation'
import {
  api,
  type TargetAllocationOut,
  type UserOut,
} from '../../lib/api'

const me: UserOut = {
  id: 'u1', email: 'd@x.com', name: 'Dani', role: 'admin',
  workspace_id: 'ws1', workspace_name: 'Família', is_active: true,
  created_at: '2026-01-01T00:00:00Z',
}

const emptyTargets: TargetAllocationOut = {
  workspace_id: 'ws1',
  CLASS: { dimension: 'CLASS', entries: [], total: '0', is_valid: false },
  COUNTRY: { dimension: 'COUNTRY', entries: [], total: '0', is_valid: false },
}

const populatedTargets: TargetAllocationOut = {
  workspace_id: 'ws1',
  CLASS: {
    dimension: 'CLASS',
    entries: [
      { key: 'REIT', target_pct: '0.4' },
      { key: 'STOCK', target_pct: '0.6' },
    ],
    total: '1',
    is_valid: true,
  },
  COUNTRY: {
    dimension: 'COUNTRY',
    entries: [
      { key: 'BR', target_pct: '0.7' },
      { key: 'US', target_pct: '0.3' },
    ],
    total: '1',
    is_valid: true,
  },
}

function renderPage() {
  return render(
    <MemoryRouter>
      <TargetAllocation />
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.restoreAllMocks()
})

describe('TargetAllocation page', () => {
  it('renders empty state with default tab "Por classe"', async () => {
    vi.spyOn(api, 'me').mockResolvedValue(me)
    vi.spyOn(api, 'getTargetAllocation').mockResolvedValue(emptyTargets)
    renderPage()
    expect(await screen.findByText(/Nenhuma meta cadastrada/)).toBeInTheDocument()
    expect(screen.getByText('Por classe').className).toMatch(/indigo/)
  })

  it('loads and renders existing entries', async () => {
    vi.spyOn(api, 'me').mockResolvedValue(me)
    vi.spyOn(api, 'getTargetAllocation').mockResolvedValue(populatedTargets)
    renderPage()
    // Wait for table to populate.
    await screen.findByLabelText(/Meta de Ação/)
    // Sum should be 100% and green.
    const sum = screen.getByTestId('ta-sum')
    expect(sum.textContent).toBe('100.00%')
    expect(sum.className).toMatch(/emerald/)
  })

  it('updates sum when user edits a value, badge turns red when ≠100', async () => {
    vi.spyOn(api, 'me').mockResolvedValue(me)
    vi.spyOn(api, 'getTargetAllocation').mockResolvedValue(populatedTargets)
    renderPage()
    const stockInput = await screen.findByLabelText(/Meta de Ação/) as HTMLInputElement
    fireEvent.change(stockInput, { target: { value: '50' } })
    const sum = screen.getByTestId('ta-sum')
    expect(sum.textContent).toBe('90.00%')
    expect(sum.className).toMatch(/red/)
    // Save button disabled when sum ≠ 100.
    expect((screen.getByTestId('ta-save') as HTMLButtonElement).disabled).toBe(true)
  })

  it('save flow: opens confirm modal, calls api.putTargetAllocation', async () => {
    vi.spyOn(api, 'me').mockResolvedValue(me)
    vi.spyOn(api, 'getTargetAllocation').mockResolvedValue(populatedTargets)
    const putSpy = vi
      .spyOn(api, 'putTargetAllocation')
      .mockResolvedValue(populatedTargets)
    renderPage()
    // Make a dirty change that keeps sum=100: 60→60 (just changes value, then back).
    const stockInput = await screen.findByLabelText(/Meta de Ação/) as HTMLInputElement
    fireEvent.change(stockInput, { target: { value: '60' } })
    // Force dirty=true via re-edit even with same value: explicit step.
    fireEvent.change(stockInput, { target: { value: '60.00' } })
    // Open confirm modal.
    const saveBtn = screen.getByTestId('ta-save') as HTMLButtonElement
    expect(saveBtn.disabled).toBe(false)
    fireEvent.click(saveBtn)
    expect(await screen.findByTestId('ta-confirm')).toBeInTheDocument()
    // Confirm.
    fireEvent.click(screen.getByText('Confirmar'))
    await waitFor(() => {
      expect(putSpy).toHaveBeenCalledWith(
        'ws1',
        'CLASS',
        expect.arrayContaining([
          expect.objectContaining({ key: 'STOCK' }),
          expect.objectContaining({ key: 'REIT' }),
        ]),
      )
    })
  })

  it('ESC closes the confirmation modal', async () => {
    vi.spyOn(api, 'me').mockResolvedValue(me)
    vi.spyOn(api, 'getTargetAllocation').mockResolvedValue(populatedTargets)
    renderPage()
    const stockInput = await screen.findByLabelText(/Meta de Ação/) as HTMLInputElement
    fireEvent.change(stockInput, { target: { value: '60.00' } })
    fireEvent.click(screen.getByTestId('ta-save'))
    expect(await screen.findByTestId('ta-confirm')).toBeInTheDocument()
    fireEvent.keyDown(document, { key: 'Escape' })
    await waitFor(() => {
      expect(screen.queryByTestId('ta-confirm')).toBeNull()
    })
  })

  it('switching tabs swaps CLASS ↔ COUNTRY entries', async () => {
    vi.spyOn(api, 'me').mockResolvedValue(me)
    vi.spyOn(api, 'getTargetAllocation').mockResolvedValue(populatedTargets)
    renderPage()
    await screen.findByLabelText(/Meta de Ação/)
    // Country tab.
    fireEvent.click(screen.getByText('Por país'))
    await waitFor(() => {
      expect(screen.getByLabelText(/Meta de Brasil/)).toBeInTheDocument()
      expect(screen.getByLabelText(/Meta de EUA/)).toBeInTheDocument()
    })
    // Back to class tab.
    fireEvent.click(screen.getByText('Por classe'))
    await waitFor(() => {
      expect(screen.getByLabelText(/Meta de Ação/)).toBeInTheDocument()
    })
  })

  it('"Distribuir igualmente" sets equal pct on all current rows', async () => {
    vi.spyOn(api, 'me').mockResolvedValue(me)
    vi.spyOn(api, 'getTargetAllocation').mockResolvedValue(populatedTargets)
    renderPage()
    await screen.findByLabelText(/Meta de Ação/)
    fireEvent.click(screen.getByText('Distribuir igualmente'))
    const sum = screen.getByTestId('ta-sum')
    expect(sum.textContent).toBe('100.00%')
    const stockInput = screen.getByLabelText(/Meta de Ação/) as HTMLInputElement
    expect(stockInput.value).toBe('50.00')
  })
})
