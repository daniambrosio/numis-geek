import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import BulkExtractReviewModal from './BulkExtractReviewModal'
import {
  api,
  type BulkApplyDetailOut,
  type BulkExtractJobOut,
  type SnapshotPendencyOut,
  type FinancialInstitutionOut,
} from '../lib/api'

// Spec 57 tornou o modal server-authoritative: as três seções vêm de
// `previewExtraction`, não de classificação no cliente. Sem esse mock o
// componente renderiza tudo zerado — era por isso que estes testes estavam
// vermelhos (corrigido 2026-09-05).
const EMPTY_DETAIL: BulkApplyDetailOut = {
  applied: [], matched_no_pendency: [], orphan: [],
  pendency_not_in_extract: [], auto_skipped: [],
}

function mockPreview(detail: Partial<BulkApplyDetailOut>) {
  return vi.spyOn(api, 'previewExtraction').mockResolvedValue({
    applied_count: 0, skipped_count: 0, errors: [],
    bulk_detail: { ...EMPTY_DETAIL, ...detail },
  })
}

beforeEach(() => {
  vi.restoreAllMocks()
  vi.spyOn(api, 'listFinancialInstitutions').mockResolvedValue([
    {
      id: 'fi-xp', long_name: 'XP', short_name: 'XP',
      logo_slug: 'xp', country: 'BR', is_active: true,
    } as FinancialInstitutionOut,
  ])
  mockPreview({})
})

function makePendency(over: Partial<SnapshotPendencyOut> = {}): SnapshotPendencyOut {
  return {
    id: 'pen-1', snapshot_id: 'snap-1',
    asset_id: 'a-petr', asset_ticker: 'PETR4', asset_name: 'Petrobras',
    asset_currency: 'BRL',
    asset_institution_short_name: 'XP',
    reason: 'MANUAL_SOURCE', action_type: 'EDIT_PRICE',
    detail: null, resolved_at: null, resolved_by: null,
    resolution_note: null, created_at: '2026-05-25T00:00:00Z',
    previous_unit_price: '30.00', previous_period_end: '2026-04-30',
    ...over,
  }
}

function makeJob(positions: any[]): BulkExtractJobOut {
  return {
    id: 'job-1',
    status: 'EXTRACTED',
    extracted_json: { positions },
    error_message: null,
  }
}

describe('BulkExtractReviewModal', () => {
  it('renders three sections with counts', async () => {
    const job = makeJob([
      { ticker_normalized: 'PETR4', ticker_raw: 'PETR4', unit_price: 38.5 },  // matched
      { ticker_normalized: 'ABEV3', ticker_raw: 'ABEV3', unit_price: 12.0 },  // orphan
    ])
    mockPreview({
      applied: [{
        pendency_id: '1', asset_id: 'a-petr', ticker: 'PETR4',
        asset_name: 'Petrobras', currency: 'BRL',
        institution_short_name: 'XP',
        new_price: '38.50', previous_price: '30.00',
      }],
      orphan: [{ ticker: 'ABEV3', unit_price: '12.00', currency: 'BRL' }],
      pendency_not_in_extract: [{
        pendency_id: '2', asset_id: 'a-aapl', ticker: 'AAPL',
        asset_name: 'Apple', currency: 'USD',
        institution_short_name: 'Avenue',
      }],
    })
    render(<BulkExtractReviewModal
      job={job}
      pendencies={[
        makePendency({ id: '1', asset_ticker: 'PETR4' }),
        makePendency({ id: '2', asset_id: 'a-aapl', asset_ticker: 'AAPL', asset_institution_short_name: 'Avenue' }),
      ]}
      onApplied={() => {}}
      onClose={() => {}}
    />)
    await waitFor(() => expect(
      screen.getByTestId('bulk-section-matched'),
    ).toHaveTextContent(/Casadas \(1\)/))
    expect(screen.getByTestId('bulk-section-uncovered')).toHaveTextContent(/Pendências não cobertas \(1\)/)
    expect(screen.getByTestId('bulk-section-orphan')).toHaveTextContent(/Linhas órfãs \(1\)/)
  })

  it('Apply button calls confirmExtraction with institution_short_name when chosen', async () => {
    const job = makeJob([{ ticker_normalized: 'PETR4', ticker_raw: 'PETR4', unit_price: 38.5 }])
    mockPreview({
      applied: [{
        pendency_id: 'pen-1', asset_id: 'a-petr', ticker: 'PETR4',
        asset_name: 'Petrobras', currency: 'BRL',
        institution_short_name: 'XP',
        new_price: '38.50', previous_price: '30.00',
      }],
    })
    vi.spyOn(api, 'confirmExtraction').mockResolvedValue({
      applied_count: 1, skipped_count: 0, errors: [], bulk_detail: null,
    })
    const onApplied = vi.fn()

    render(<BulkExtractReviewModal
      job={job}
      pendencies={[makePendency()]}
      onApplied={onApplied}
      onClose={() => {}}
    />)

    // Wait for FI list to populate.
    await waitFor(() => expect(screen.getByTestId('bulk-review-fi-select')).toBeInTheDocument())
    await userEvent.selectOptions(screen.getByTestId('bulk-review-fi-select'), 'XP')
    await userEvent.click(screen.getByTestId('bulk-review-apply'))

    await waitFor(() => expect(api.confirmExtraction).toHaveBeenCalledWith('job-1', {
      institution_short_name: 'XP',
      manual_mappings: null,
      manual_prices: null,
      acknowledge_integrity: false,
    }))
    expect(onApplied).toHaveBeenCalledWith(1, false)
  })

  // ── Bug Avenue Out/26 (2026-11-02) ─────────────────────────────────────────

  const APPLIED_PETR = {
    pendency_id: 'pen-1', asset_id: 'a-petr', ticker: 'PETR4',
    asset_name: 'Petrobras', currency: 'BRL',
    institution_short_name: 'XP',
    new_price: '38.50', previous_price: '30.00',
  }

  it('integrity issues block Apply until the user acknowledges', async () => {
    const job = makeJob([{ ticker_normalized: 'PETR4', ticker_raw: 'PETR4', unit_price: 38.5 }])
    mockPreview({
      applied: [APPLIED_PETR],
      integrity_issues: ['Seção “Ações”: as 1 linhas somam R$ 3,850.00, o extrato mostra R$ 10,000.00'],
    })
    vi.spyOn(api, 'confirmExtraction').mockResolvedValue({
      applied_count: 1, skipped_count: 0, errors: [], bulk_detail: null,
    })
    render(<BulkExtractReviewModal
      job={job} pendencies={[makePendency()]} onApplied={() => {}} onClose={() => {}}
    />)
    await waitFor(() => expect(screen.getByTestId('bulk-integrity-issues')).toHaveTextContent('Ações'))
    expect(screen.getByTestId('bulk-review-apply')).toBeDisabled()

    await userEvent.click(screen.getByTestId('bulk-integrity-ack'))
    expect(screen.getByTestId('bulk-review-apply')).toBeEnabled()
    await userEvent.click(screen.getByTestId('bulk-review-apply'))
    await waitFor(() => expect(api.confirmExtraction).toHaveBeenCalledWith(
      'job-1', expect.objectContaining({ acknowledge_integrity: true }),
    ))
  })

  it('after applying with warnings shows what was recorded, not a re-classified preview', async () => {
    const job = makeJob([{ ticker_normalized: 'PETR4', ticker_raw: 'PETR4', unit_price: 38.5 }])
    mockPreview({ applied: [APPLIED_PETR] })
    vi.spyOn(api, 'confirmExtraction').mockResolvedValue({
      applied_count: 1, skipped_count: 0,
      errors: ['PETR4: qty×price (3800.00) ≠ mv (3850.00); unit_price recomputed'],
      bulk_detail: {
        applied: [APPLIED_PETR], matched_no_pendency: [], orphan: [],
        pendency_not_in_extract: [], auto_skipped: [],
      },
    })
    const rejectSpy = vi.spyOn(api, 'rejectExtraction').mockResolvedValue({} as never)
    const onApplied = vi.fn()
    const onClose = vi.fn()
    render(<BulkExtractReviewModal
      job={job} pendencies={[makePendency()]} onApplied={onApplied} onClose={onClose}
    />)
    await waitFor(() => expect(screen.getByTestId('bulk-review-apply')).toBeEnabled())
    await userEvent.click(screen.getByTestId('bulk-review-apply'))

    const summary = await screen.findByTestId('bulk-applied-summary')
    expect(summary).toHaveTextContent('1 pendência resolvida')
    expect(summary).toHaveTextContent('PETR4')
    expect(summary).toHaveTextContent('38,50')
    expect(screen.getByTestId('bulk-applied-warnings')).toHaveTextContent('unit_price recomputed')
    expect(screen.queryByTestId('bulk-section-matched')).not.toBeInTheDocument()
    expect(onApplied).toHaveBeenCalledWith(1, true)

    // Job já está CONFIRMED: fechar não pode disparar reject (dava 409).
    await userEvent.click(screen.getByTestId('bulk-applied-close'))
    expect(onClose).toHaveBeenCalled()
    await userEvent.click(screen.getByLabelText('Fechar'))
    expect(rejectSpy).not.toHaveBeenCalled()
  })

  it('orphan without unit price suggests the line market value when mapped', async () => {
    const job = makeJob([{ ticker_raw: 'T 4.625 15/11/44', unit_price: null }])
    mockPreview({
      orphan: [{ ticker: 'T 4.625 15/11/44', unit_price: null, market_value: '2828.37', currency: 'USD' }],
    })
    render(<BulkExtractReviewModal
      job={job} pendencies={[makePendency()]} onApplied={() => {}} onClose={() => {}}
    />)
    const orphan = await screen.findByTestId('bulk-orphan-T 4.625 15/11/44')
    expect(orphan).toHaveTextContent('2.828,37')
  })

  it('Apply button disabled when no matches', () => {
    const job = makeJob([{ ticker_normalized: 'XXXX', unit_price: 1.0 }])
    render(<BulkExtractReviewModal
      job={job}
      pendencies={[makePendency()]}
      onApplied={() => {}}
      onClose={() => {}}
    />)
    expect(screen.getByTestId('bulk-review-apply')).toBeDisabled()
  })
})
