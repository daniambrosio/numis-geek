import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import BulkIncomeReviewModal from './BulkIncomeReviewModal'
import { api, type BulkExtractJobOut, type ExtractionApplyResultOut } from '../lib/api'

// O modal é server-authoritative (2026-09-05): quem resolve pra qual ativo
// cada provento vai é `previewExtraction`. Antes lia extracted_json direto
// com o campo errado (`ticker` vs `ticker_raw`) e mostrava "—" em tudo.
function mockPreview(over: Partial<ExtractionApplyResultOut> & {
  applied?: unknown[]; orphan?: unknown[]; matched_no_pendency?: unknown[]
}) {
  const { applied = [], orphan = [], matched_no_pendency = [], ...rest } = over
  return vi.spyOn(api, 'previewExtraction').mockResolvedValue({
    applied_count: applied.length, skipped_count: orphan.length + matched_no_pendency.length,
    errors: [],
    bulk_detail: {
      applied, orphan, matched_no_pendency,
      pendency_not_in_extract: [], auto_skipped: [],
    } as unknown as ExtractionApplyResultOut['bulk_detail'],
    ...rest,
  })
}

const JOB: BulkExtractJobOut = {
  id: 'job-inc', status: 'EXTRACTED',
  // Payload real usa ticker_raw — o modal NÃO deve depender disso.
  extracted_json: { events: [{ ticker_raw: 'WMT', event_date: '2026-08-04', type: 'DIVIDEND' }] },
  error_message: null,
  institution_short_name: 'Avenue',
  snapshot_period_end_date: '2026-08-31',
}

const ROW = {
  external_id: 'x1', event_date: '2026-08-04', type: 'DIVIDEND', currency: 'USD',
  gross_amount: '60.14', tax_amount: '18.04', net_amount: '42.10',
  institution_short_name: 'Avenue',
}

beforeEach(() => {
  vi.restoreAllMocks()
  vi.spyOn(api, 'rejectExtraction').mockResolvedValue({} as never)
})

describe('BulkIncomeReviewModal', () => {
  it('mostra ticker e nome do ativo resolvido pelo backend', async () => {
    mockPreview({
      applied: [
        { ...ROW, ticker: 'WMT', asset_id: 'a-wmt', asset_name: 'Walmart Inc' },
        { ...ROW, ticker: null, asset_id: null, asset_name: null, type: 'SECURITIES_LENDING', net_amount: '0.47' },
      ],
    })
    render(<BulkIncomeReviewModal job={JOB} onApplied={() => {}} onClose={() => {}} />)
    await waitFor(() => expect(screen.getByTestId('income-row-0')).toBeInTheDocument())
    expect(api.previewExtraction).toHaveBeenCalledWith('job-inc')
    expect(screen.getByTestId('income-row-0')).toHaveTextContent('WMT')
    expect(screen.getByTestId('income-row-asset-0')).toHaveTextContent('Walmart Inc')
    expect(screen.getByTestId('income-row-asset-1')).toHaveTextContent('sem ativo (aluguel)')
    expect(screen.getByTestId('income-review-apply')).toHaveTextContent('Registrar 2 proventos')
  })

  it('separa órfãos (sem ativo) e já registrados, e não os conta no botão', async () => {
    mockPreview({
      applied: [{ ...ROW, ticker: 'WMT', asset_id: 'a-wmt', asset_name: 'Walmart Inc' }],
      orphan: [{ ...ROW, ticker: 'T 4.25 15/11/34', asset_id: null, asset_name: null, type: 'INTEREST' }],
      matched_no_pendency: [{ ...ROW, ticker: 'KO', asset_id: 'a-ko', asset_name: 'Coca-Cola', distribution_id: 'd1' }],
      errors: ['3 evento(s) fora do período 2026-08-01–2026-08-31 ignorado(s)'],
    })
    render(<BulkIncomeReviewModal job={JOB} onApplied={() => {}} onClose={() => {}} />)
    await waitFor(() => expect(screen.getByTestId('income-orphans')).toBeInTheDocument())
    expect(screen.getByTestId('income-orphans')).toHaveTextContent('1 sem ativo correspondente na Avenue')
    expect(screen.getByTestId('income-orphans')).toHaveTextContent('T 4.25 15/11/34')
    expect(screen.getByTestId('income-duplicates')).toHaveTextContent('1 já registrado')
    expect(screen.getByTestId('income-duplicates')).toHaveTextContent('Coca-Cola')
    expect(screen.getByText(/fora do período/)).toBeInTheDocument()
    expect(screen.getByTestId('income-review-apply')).toHaveTextContent('Registrar 1 provento')
  })

  it('confirma via confirmExtraction e devolve applied_count', async () => {
    mockPreview({ applied: [{ ...ROW, ticker: 'WMT', asset_id: 'a-wmt', asset_name: 'Walmart Inc' }] })
    vi.spyOn(api, 'confirmExtraction').mockResolvedValue({
      applied_count: 1, skipped_count: 0, errors: [], bulk_detail: null,
    })
    const onApplied = vi.fn()
    render(<BulkIncomeReviewModal job={JOB} onApplied={onApplied} onClose={() => {}} />)
    await waitFor(() => expect(screen.getByTestId('income-row-0')).toBeInTheDocument())
    await userEvent.click(screen.getByTestId('income-review-apply'))
    await waitFor(() => expect(onApplied).toHaveBeenCalledWith(1))
    expect(api.confirmExtraction).toHaveBeenCalledWith('job-inc', {})
  })
})
