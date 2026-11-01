import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import BankImportReviewModal from './BankImportReviewModal'
import {
  api, type AccountOut, type BankImportPreview, type BankImportRow, type CategoryOut, type StatementImportOut,
} from '../lib/api'
import { countDecisions, initialDecisions } from '../lib/bankImport'

const JOB: StatementImportOut = {
  id: 'job-1', status: 'EXTRACTED', source_hint: 'BANK_STATEMENT', attachment_id: 'att-1',
  filename: 'itau-out.ofx', checking_account_id: 'acc-1', credit_card_account_id: null,
  statement_period_start: '2026-10-01', statement_period_end: '2026-10-31', line_count: 4,
  transaction_count: 0, error_message: null, cost_usd: null, created_at: '2026-10-31T10:00:00',
  confirmed_at: null, resumed: false,
}

function row(over: Partial<BankImportRow>): BankImportRow {
  return {
    row_id: 'r0', index: 0, event_date: '2026-10-05', original_date: '2026-10-05',
    description: 'PADARIA', amount: '-12.00', currency: 'BRL', installment_number: null,
    installment_total: null, is_invoice_payment: false, bucket: 'new', actions: ['import', 'skip'],
    default_action: 'import', warning: null, party: { mode: 'new', new_party_name: 'PADARIA', alias: 'PADARIA' },
    ...over,
  }
}

const ROWS: BankImportRow[] = [
  row({ row_id: 'r0' }),
  row({
    row_id: 'r1', index: 1, description: 'CONTA DE LUZ', amount: '-210.55', bucket: 'duplicate',
    actions: ['reconcile', 'skip', 'import_anyway'], default_action: 'reconcile',
    duplicate: { transaction_id: 'tx-manual', is_reconciled: false, reason: 'fingerprint' },
  }),
  row({
    row_id: 'r2', index: 2, description: 'MERCADO X', amount: '-100.00', bucket: 'duplicate',
    actions: ['skip', 'import_anyway'], default_action: 'skip',
    duplicate: { transaction_id: 'tx-old', is_reconciled: true, reason: 'fingerprint' },
  }),
  row({
    row_id: 'r3', index: 3, description: 'TED ALUGUEL', amount: '-3000.00', bucket: 'scheduled',
    actions: ['settle', 'import', 'skip'], default_action: 'settle',
    scheduled: {
      occurrence_id: 'occ-a',
      candidates: [
        { occurrence_id: 'occ-a', description: 'Aluguel', due_date: '2026-10-10', amount: '3000.00', currency: 'BRL', direction: 'PAYABLE', category_id: null, party_id: null },
        { occurrence_id: 'occ-b', description: 'Aluguel', due_date: '2026-10-13', amount: '3000.00', currency: 'BRL', direction: 'PAYABLE', category_id: null, party_id: null },
      ],
    },
  }),
]

function preview(over: Partial<BankImportPreview> = {}): BankImportPreview {
  return {
    rows: ROWS, invoice: null, warnings: [], period: { start: '2026-10-01', end: '2026-10-31' },
    overlaps: [{ job_id: 'job-0', start: '2026-09-15', end: '2026-10-15', duplicate_count: 2 }],
    counts: { new: 1, duplicate: 2, scheduled: 1 },
    ...over,
  }
}

function mockPreview(p: BankImportPreview) {
  return vi.spyOn(api, 'previewExtraction').mockResolvedValue({
    applied_count: 0, skipped_count: 0, errors: [], bulk_detail: null, bank_import: p,
  })
}

const CATS: CategoryOut[] = [
  { id: 'root', name: 'Moradia', parent_id: null, kind: null, color: '#0f0', is_active: true } as CategoryOut,
  { id: 'sub', name: 'Aluguel', parent_id: 'root', kind: 'EXPENSE', color: null, is_active: true } as CategoryOut,
]

beforeEach(() => {
  vi.restoreAllMocks()
  vi.spyOn(api, 'listParties').mockResolvedValue([])
  vi.spyOn(api, 'rejectExtraction').mockResolvedValue({} as never)
})

describe('BankImportReviewModal', () => {
  it('mostra buckets, banner de overlap e o contador Importar · Reconciliar', async () => {
    mockPreview(preview())
    render(<BankImportReviewModal job={JOB} accounts={[]} categories={CATS} onApplied={() => {}} onClose={() => {}} />)
    await waitFor(() => expect(screen.getByTestId('bucket-new')).toBeInTheDocument())
    expect(api.previewExtraction).toHaveBeenCalledWith('job-1')
    expect(screen.getByTestId('overlap-banner')).toHaveTextContent('Overlap com import de 15/09–15/10 — 2 linhas caíram como duplicatas')
    expect(screen.getByTestId('bucket-duplicate')).toHaveTextContent('Duplicadas')
    expect(screen.getByTestId('bucket-scheduled')).toHaveTextContent('Quita conta a pagar/receber')
    // novas (1) + quita (1) criam; a manual não reconciliada é Reconciliar por default
    expect(screen.getByTestId('bank-import-apply')).toHaveTextContent('Importar 2 · Reconciliar 1')
    expect(screen.getByTestId('row-r1')).toHaveTextContent('manual, não reconciliada')
  })

  it('aplica com as decisões editadas (ação, categoria, fornecedor, outra conta a pagar)', async () => {
    mockPreview(preview())
    const confirm = vi.spyOn(api, 'confirmExtraction').mockResolvedValue({
      applied_count: 3, skipped_count: 1, errors: [], bulk_detail: null,
      bank_import: { created: 2, reconciled: 0, skipped: 2, paid_invoices: 0, settled: 1, new_parties: 1, invoice_id: null },
    })
    const onApplied = vi.fn()
    render(<BankImportReviewModal job={JOB} accounts={[]} categories={CATS} onApplied={onApplied} onClose={() => {}} />)
    await waitFor(() => expect(screen.getByTestId('row-r0')).toBeInTheDocument())

    const r0 = within(screen.getByTestId('row-r0'))
    await userEvent.selectOptions(r0.getByLabelText('Categoria'), 'sub')
    await userEvent.selectOptions(r0.getByLabelText('Fornecedor/Cliente'), 'none')
    await userEvent.selectOptions(screen.getByTestId('action-r1'), 'skip')
    await userEvent.selectOptions(within(screen.getByTestId('row-r3')).getByLabelText('Conta a pagar/receber'), 'occ-b')
    expect(screen.getByTestId('bank-import-apply')).toHaveTextContent('Importar 2 · Reconciliar 0')

    await userEvent.click(screen.getByTestId('bank-import-apply'))
    await waitFor(() => expect(onApplied).toHaveBeenCalled())
    const decisions = confirm.mock.calls[0][1]!.bank_decisions!
    expect(decisions.r0).toMatchObject({ action: 'import', category_id: 'sub', no_party: true })
    expect(decisions.r1.action).toBe('skip')
    expect(decisions.r2.action).toBe('skip')
    expect(decisions.r3).toMatchObject({ action: 'settle', occurrence_id: 'occ-b' })
  })

  it('erro no apply vai pro toast e o botão volta a ficar ativo', async () => {
    mockPreview(preview())
    let reject: (e: Error) => void = () => {}
    vi.spyOn(api, 'confirmExtraction').mockImplementation(() => new Promise((_, rj) => { reject = rj }))
    render(<BankImportReviewModal job={JOB} accounts={[]} categories={CATS} onApplied={() => {}} onClose={() => {}} />)
    await waitFor(() => expect(screen.getByTestId('bank-import-apply')).toBeEnabled())
    await userEvent.click(screen.getByTestId('bank-import-apply'))
    expect(screen.getByTestId('bank-import-apply')).toBeDisabled()  // spinner while applying
    reject(new Error('Ação inválida'))
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Ação inválida'))
    expect(screen.getByTestId('bank-import-apply')).toBeEnabled()
  })

  it('pagamento de fatura do cartão exige a conta de origem', async () => {
    const accounts = [{ id: 'acc-9', name: 'Itaú CC', account_type: 'checking', is_active: true, currency: 'BRL' } as AccountOut]
    mockPreview(preview({
      overlaps: [],
      rows: [row({
        row_id: 'r0', description: 'PAGAMENTO RECEBIDO', amount: '800.00', bucket: 'invoice_payment',
        is_invoice_payment: true, actions: ['pay', 'skip'], default_action: 'skip', party: { mode: 'none' },
        invoice_payment: { kind: 'card_payment_line', invoice_id: 'inv-1', card_name: 'Nubank', close_date: '2026-09-05', status: 'CLOSED', payment_account_id: null },
      })],
    }))
    render(<BankImportReviewModal job={{ ...JOB, source_hint: 'CARD_INVOICE' }} accounts={accounts} categories={CATS} onApplied={() => {}} onClose={() => {}} />)
    await waitFor(() => expect(screen.getByTestId('row-r0')).toBeInTheDocument())
    expect(screen.getByRole('dialog')).toHaveAccessibleName('Revisar fatura importada')
    await userEvent.selectOptions(screen.getByTestId('action-r0'), 'pay')
    expect(screen.getByTestId('bank-import-apply')).toBeDisabled()
    await userEvent.selectOptions(screen.getByLabelText('Conta do pagamento'), 'acc-9')
    expect(screen.getByTestId('bank-import-apply')).toBeEnabled()
    expect(screen.getByTestId('bank-import-apply')).toHaveTextContent('Importar 1 · Reconciliar 0')
  })

  it('ESC fecha sem descartar; Descartar rejeita o job', async () => {
    mockPreview(preview())
    const onClose = vi.fn()
    render(<BankImportReviewModal job={JOB} accounts={[]} categories={CATS} onApplied={() => {}} onClose={onClose} />)
    await waitFor(() => expect(screen.getByTestId('bucket-new')).toBeInTheDocument())
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(onClose).toHaveBeenCalledTimes(1)
    expect(api.rejectExtraction).not.toHaveBeenCalled()
    await userEvent.click(screen.getByText('Descartar'))
    await waitFor(() => expect(api.rejectExtraction).toHaveBeenCalledWith('job-1', 'descartado pelo usuário'))
  })

  it('duplicadas que só serão puladas começam recolhidas', async () => {
    mockPreview(preview({ rows: [ROWS[0], ROWS[2]] }))
    render(<BankImportReviewModal job={JOB} accounts={[]} categories={CATS} onApplied={() => {}} onClose={() => {}} />)
    await waitFor(() => expect(screen.getByTestId('bucket-duplicate')).toBeInTheDocument())
    expect(screen.queryByTestId('row-r2')).not.toBeInTheDocument()
    await userEvent.click(within(screen.getByTestId('bucket-duplicate')).getByRole('button'))
    expect(screen.getByTestId('row-r2')).toBeInTheDocument()
  })
})

describe('BankImportReviewModal — audit 2026-10-31', () => {
  it('X e ESC não fecham com o apply em voo; o erro aparece', async () => {
    mockPreview(preview())
    let reject: (e: Error) => void = () => {}
    vi.spyOn(api, 'confirmExtraction').mockImplementation(() => new Promise((_, rj) => { reject = rj }))
    const onClose = vi.fn()
    render(<BankImportReviewModal job={JOB} accounts={[]} categories={CATS} onApplied={() => {}} onClose={onClose} />)
    await waitFor(() => expect(screen.getByTestId('bank-import-apply')).toBeEnabled())
    await userEvent.click(screen.getByTestId('bank-import-apply'))
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.getByRole('button', { name: 'Fechar' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: 'Fechar' }))
    expect(onClose).not.toHaveBeenCalled()
    reject(new Error('Fatura já paga.'))
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Fatura já paga.'))
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('linha em outra moeda vai pra "Não importáveis" e só pode ser pulada', async () => {
    mockPreview(preview({ overlaps: [], rows: [row({
      row_id: 'r0', bucket: 'blocked', actions: ['skip'], default_action: 'skip', party: { mode: 'none' },
      warning: 'Linha em USD numa conta em BRL — não importável',
    })] }))
    render(<BankImportReviewModal job={JOB} accounts={[]} categories={CATS} onApplied={() => {}} onClose={() => {}} />)
    await waitFor(() => expect(screen.getByTestId('bucket-blocked')).toHaveTextContent('Não importáveis'))
    expect(within(screen.getByTestId('action-r0')).getAllByRole('option').map(o => o.textContent)).toEqual(['Pular'])
    expect(screen.getByTestId('bank-import-apply')).toBeDisabled()
  })

  it('conta do pagamento de fatura só lista contas na moeda da fatura', async () => {
    const accounts = [
      { id: 'brl', name: 'Itaú CC', account_type: 'checking', is_active: true, currency: 'BRL' } as AccountOut,
      { id: 'usd', name: 'Nomad USD', account_type: 'checking', is_active: true, currency: 'USD' } as AccountOut,
    ]
    mockPreview(preview({ overlaps: [], rows: [row({
      row_id: 'r0', description: 'PAGAMENTO RECEBIDO', amount: '800.00', bucket: 'invoice_payment',
      is_invoice_payment: true, actions: ['pay', 'skip'], default_action: 'pay', party: { mode: 'none' },
      invoice_payment: { kind: 'card_payment_line', invoice_id: 'inv-1', status: 'CLOSED', payment_account_id: null },
    })] }))
    render(<BankImportReviewModal job={{ ...JOB, source_hint: 'CARD_INVOICE' }} accounts={accounts} categories={CATS} onApplied={() => {}} onClose={() => {}} />)
    await waitFor(() => expect(screen.getByLabelText('Conta do pagamento')).toBeInTheDocument())
    const opts = within(screen.getByLabelText('Conta do pagamento')).getAllByRole('option').map(o => o.textContent)
    expect(opts).toEqual(['Conta de origem…', 'Itaú CC'])
  })

  it('vincular débito já lançado conta como Reconciliar', async () => {
    mockPreview(preview({ overlaps: [], rows: [row({
      row_id: 'r0', description: 'PAGAMENTO RECEBIDO', amount: '1500.00', bucket: 'invoice_payment',
      is_invoice_payment: true, actions: ['link', 'skip'], default_action: 'link', party: { mode: 'none' },
      invoice_payment: { kind: 'card_payment_line', invoice_id: 'inv-1', status: 'CLOSED', payment_account_id: 'acc-1',
        existing_debit: { transaction_id: 'tx-9', event_date: '2026-06-14' } },
    })] }))
    render(<BankImportReviewModal job={{ ...JOB, source_hint: 'CARD_INVOICE' }} accounts={[]} categories={CATS} onApplied={() => {}} onClose={() => {}} />)
    await waitFor(() => expect(screen.getByTestId('row-r0')).toHaveTextContent('débito já lançado em 14/06/26'))
    expect(screen.getByTestId('action-r0')).toHaveValue('link')
    expect(screen.getByTestId('bank-import-apply')).toHaveTextContent('Importar 0 · Reconciliar 1')
  })

  it('quitar conta a pagar mostra o fornecedor da conta escolhida, não "nova"', async () => {
    const sched = ROWS[3].scheduled!
    mockPreview(preview({ overlaps: [], rows: [{
      ...ROWS[3], party: { mode: 'none', from_occurrence: true },
      scheduled: { ...sched, candidates: [
        { ...sched.candidates[0], party_name: 'Imobiliária Z' },
        { ...sched.candidates[1], party_name: null },
      ] },
    }] }))
    render(<BankImportReviewModal job={JOB} accounts={[]} categories={CATS} onApplied={() => {}} onClose={() => {}} />)
    await waitFor(() => expect(screen.getByTestId('row-r3')).toBeInTheDocument())
    const r3 = within(screen.getByTestId('row-r3'))
    expect(r3.getByLabelText('Fornecedor/Cliente')).toHaveDisplayValue('Imobiliária Z (da conta a pagar/receber)')
    await userEvent.selectOptions(r3.getByLabelText('Conta a pagar/receber'), 'occ-b')
    expect(r3.getByLabelText('Fornecedor/Cliente')).toHaveDisplayValue('Sem fornecedor/cliente (da conta a pagar/receber)')
  })
})

describe('bankImport helpers', () => {
  it('initialDecisions usa o default e a conta/ocorrência sugeridas', () => {
    const d = initialDecisions(ROWS)
    expect(d.r1.action).toBe('reconcile')
    expect(d.r3.occurrence_id).toBe('occ-a')
    expect(countDecisions(d)).toEqual({ toImport: 2, toReconcile: 1 })
  })
})
