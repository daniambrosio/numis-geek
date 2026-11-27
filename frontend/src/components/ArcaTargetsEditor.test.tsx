/* Spec 85 — aba ARCA da Alocação alvo. */
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'

import ArcaTargetsEditor from './ArcaTargetsEditor'
import { api, type TargetAllocationOut } from '../lib/api'

const empty: TargetAllocationOut = {
  workspace_id: 'ws1',
  CLASS: { dimension: 'CLASS', entries: [], total: '0', is_valid: false },
  COUNTRY: { dimension: 'COUNTRY', entries: [], total: '0', is_valid: false },
  ARCA: { dimension: 'ARCA', entries: [], total: '0', is_valid: false },
  ARCA_SUB: { dimension: 'ARCA_SUB', entries: [], total: '0', is_valid: false },
}

beforeEach(() => vi.restoreAllMocks())

describe('ArcaTargetsEditor', () => {
  it('preset fills 25% per letter and saves both dimensions', async () => {
    const put = vi.spyOn(api, 'putTargetAllocation').mockResolvedValue(empty)
    const onSaved = vi.fn()
    render(<ArcaTargetsEditor workspaceId="ws1" data={empty} onSaved={onSaved} />)
    fireEvent.click(screen.getByTestId('arca-preset'))
    expect(screen.getByTestId('arca-sum').textContent).toBe('Total: 100.00%')
    fireEvent.click(screen.getByTestId('arca-save'))
    fireEvent.click(await screen.findByTestId('arca-confirm'))
    await waitFor(() => expect(onSaved).toHaveBeenCalled())
    expect(put).toHaveBeenCalledWith('ws1', 'ARCA', expect.arrayContaining([
      { key: 'CASH', target_pct: '0.2500', min_pct: '0.1000', max_pct: '0.4000' },
    ]))
    expect(put).toHaveBeenCalledWith('ws1', 'ARCA_SUB', expect.arrayContaining([
      { key: 'CASH_INFLATION', target_pct: '0.3334' },
    ]))
  })

  it('blocks save when a letter is outside its band or subs do not sum 100', () => {
    render(<ArcaTargetsEditor workspaceId="ws1" data={empty} onSaved={() => {}} />)
    fireEvent.click(screen.getByTestId('arca-preset'))
    fireEvent.change(screen.getByLabelText('meta CASH'), { target: { value: '45' } })
    fireEvent.change(screen.getByLabelText('meta GLOBAL'), { target: { value: '5' } })
    expect((screen.getByTestId('arca-save') as HTMLButtonElement).disabled).toBe(true)
    expect(screen.getByTestId('arca-problems').textContent).toMatch(/fora da banda/)
    fireEvent.change(screen.getByLabelText('meta CASH'), { target: { value: '25' } })
    fireEvent.change(screen.getByLabelText('meta GLOBAL'), { target: { value: '25' } })
    fireEvent.change(screen.getByLabelText('sub CASH_POST_FIXED'), { target: { value: '50' } })
    expect(screen.getByTestId('arca-problems').textContent).toMatch(/Caixa: subcategorias/)
  })

  it('ESC closes the confirm dialog', async () => {
    render(<ArcaTargetsEditor workspaceId="ws1" data={empty} onSaved={() => {}} />)
    fireEvent.click(screen.getByTestId('arca-preset'))
    fireEvent.click(screen.getByTestId('arca-save'))
    expect(await screen.findByTestId('arca-confirm')).toBeInTheDocument()
    fireEvent.keyDown(document, { key: 'Escape' })
    await waitFor(() => expect(screen.queryByTestId('arca-confirm')).toBeNull())
  })

  it('loads existing targets as percentages', () => {
    const data: TargetAllocationOut = {
      ...empty,
      ARCA: {
        dimension: 'ARCA', total: '1', is_valid: true,
        entries: [{ key: 'CASH', target_pct: '0.35', min_pct: '0.2', max_pct: '0.5' }],
      },
    }
    render(<ArcaTargetsEditor workspaceId="ws1" data={data} onSaved={() => {}} />)
    expect((screen.getByLabelText('meta CASH') as HTMLInputElement).value).toBe('35')
    expect((screen.getByLabelText('max CASH') as HTMLInputElement).value).toBe('50')
  })
})
