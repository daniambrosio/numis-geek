import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import BulkExtractReviewModal from './BulkExtractReviewModal'
import {
  api,
  type BulkExtractJobOut,
  type SnapshotPendencyOut,
  type FinancialInstitutionOut,
} from '../lib/api'

beforeEach(() => {
  vi.restoreAllMocks()
  vi.spyOn(api, 'listFinancialInstitutions').mockResolvedValue([
    {
      id: 'fi-xp', long_name: 'XP', short_name: 'XP',
      logo_slug: 'xp', country: 'BR', is_active: true,
    } as FinancialInstitutionOut,
  ])
})

function makePendency(over: Partial<SnapshotPendencyOut> = {}): SnapshotPendencyOut {
  return {
    id: 'pen-1', snapshot_id: 'snap-1',
    asset_id: 'a-petr', asset_ticker: 'PETR4', asset_name: 'Petrobras',
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
  it('renders three sections with counts', () => {
    const job = makeJob([
      { ticker_normalized: 'PETR4', unit_price: 38.5 },     // matched
      { ticker_normalized: 'ABEV3', unit_price: 12.0 },     // orphan
    ])
    render(<BulkExtractReviewModal
      job={job}
      pendencies={[
        makePendency({ id: '1', asset_ticker: 'PETR4' }),
        makePendency({ id: '2', asset_id: 'a-aapl', asset_ticker: 'AAPL', asset_institution_short_name: 'Avenue' }),
      ]}
      onApplied={() => {}}
      onClose={() => {}}
    />)
    expect(screen.getByTestId('bulk-section-matched')).toHaveTextContent(/Casadas \(1\)/)
    expect(screen.getByTestId('bulk-section-uncovered')).toHaveTextContent(/Pendências não cobertas \(1\)/)
    expect(screen.getByTestId('bulk-section-orphan')).toHaveTextContent(/Linhas órfãs \(1\)/)
  })

  it('Apply button calls confirmExtraction with institution_short_name when chosen', async () => {
    const job = makeJob([{ ticker_normalized: 'PETR4', unit_price: 38.5 }])
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
    }))
    expect(onApplied).toHaveBeenCalledWith(1)
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
