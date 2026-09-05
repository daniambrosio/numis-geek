/* Spec 81 — card "Dados do ativo" com edição inline (sem modal).
 *
 * Modo leitura: a <dl> de detalhes de sempre. Modo edição: nome, ticker,
 * CNPJ, classe, país, moeda e custodiante (a conta de investimento é
 * resolvida pela FI, regra spec 10). Salva via PATCH /assets/{id} só com
 * os campos que mudaram. Renda fixa / físico continuam editando `details`
 * pelo AssetModal ("Editar detalhes…"). */
import { useEffect, useMemo, useState } from 'react'
import { Edit2, Loader2 } from 'lucide-react'

import {
  api, type AccountOut, type AssetClass, type AssetOut, type AssetPatchRequest,
  type FinancialInstitutionOut,
} from '../../lib/api'
import {
  CLASS_LABELS, NEEDS_DETAILS, TICKER_FORBIDDEN, TICKER_REQUIRED, resolveInvestmentAccount,
} from '../../lib/assetForm'
import { fmtDate } from '../../lib/format'
import { fmtBRL } from '../../lib/money'
import { collapsedOf } from '../../lib/tokens'
import { Card, CcyPill, ClassBadge, INPUT_CLS, SectionTitle } from '../ui'
import { Detail } from './AssetDocsTab'
import CountryFlag from './CountryFlag'

interface Draft {
  name: string
  ticker: string
  cnpj: string
  asset_class: AssetClass
  country: string
  currency: 'BRL' | 'USD'
  fiId: string
}

function draftOf(asset: AssetOut): Draft {
  return {
    name: asset.name,
    ticker: asset.ticker ?? '',
    cnpj: asset.cnpj ?? '',
    asset_class: asset.asset_class,
    country: asset.country,
    currency: asset.currency,
    fiId: asset.financial_institution_id,
  }
}

/** Só os campos que mudaram — o PATCH é parcial de verdade. */
export function buildPatch(asset: AssetOut, d: Draft, accountId: string | null): AssetPatchRequest {
  const patch: AssetPatchRequest = {}
  if (d.name.trim() !== asset.name) patch.name = d.name.trim()
  const ticker = d.ticker.trim() || null
  if (ticker !== (asset.ticker ?? null)) patch.ticker = ticker
  const cnpj = d.cnpj.trim() || null
  if (cnpj !== (asset.cnpj ?? null)) patch.cnpj = cnpj
  if (d.asset_class !== asset.asset_class) patch.asset_class = d.asset_class
  if (d.country !== asset.country) patch.country = d.country
  if (d.currency !== asset.currency) patch.currency = d.currency
  if (accountId && accountId !== asset.account_id) patch.account_id = accountId
  return patch
}

interface Props {
  asset: AssetOut
  fi: FinancialInstitutionOut | null
  account: AccountOut | null
  institutions: FinancialInstitutionOut[]
  canDeactivate: boolean
  /** Resumo read-only (vem da posição / proventos já carregados no shell). */
  costBRL: number | null
  receivedBRL: number
  movementsCount: number
  lastMovementDate?: string
  /** Header "Editar ativo" manda a aba abrir já em edição. */
  autoEdit?: boolean
  onAutoEditConsumed?: () => void
  onSaved: (asset: AssetOut) => void
  onError: (msg: string) => void
  onEditDetails: () => void
  onDeactivate: () => void
}

export default function AssetDataCard({
  asset, fi, account, institutions, canDeactivate,
  costBRL, receivedBRL, movementsCount, lastMovementDate,
  autoEdit, onAutoEditConsumed, onSaved, onError, onEditDetails, onDeactivate,
}: Props) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState<Draft>(() => draftOf(asset))
  const [accounts, setAccounts] = useState<AccountOut[] | null>(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (autoEdit) { startEditing(); onAutoEditConsumed?.() }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoEdit])

  function startEditing() {
    setDraft(draftOf(asset))
    setEditing(true)
    if (accounts == null) {
      // Sysadmin vendo ativo de outro workspace: as contas têm que ser as
      // do workspace do ATIVO, não as do usuário.
      api.listAccounts(asset.workspace_id).then(setAccounts).catch(() => setAccounts([]))
    }
  }

  const resolvedAccount = useMemo(() => {
    if (draft.fiId === asset.financial_institution_id) return account
    return accounts ? resolveInvestmentAccount(accounts, draft.fiId) : null
  }, [draft.fiId, asset.financial_institution_id, account, accounts])

  const tickerRequired = TICKER_REQUIRED.includes(draft.asset_class)
  const tickerForbidden = TICKER_FORBIDDEN.includes(draft.asset_class)
  const classNeedsDetails = NEEDS_DETAILS.includes(draft.asset_class)
  const classChangedToDetails = classNeedsDetails && !NEEDS_DETAILS.includes(asset.asset_class)
  const patch = buildPatch(asset, draft, resolvedAccount?.id ?? null)
  const dirty = Object.keys(patch).length > 0
  // Violações herdadas (ativo legado com ticker em renda fixa, etc.) não
  // bloqueiam: o backend só rejeita o que o PATCH introduz. Só apontamos
  // problemas em campos que o usuário mexeu.
  const tickerTouched = draft.ticker.trim() !== (asset.ticker ?? '') || draft.asset_class !== asset.asset_class
  const cnpjTouched = draft.cnpj.trim() !== (asset.cnpj ?? '') || draft.asset_class !== asset.asset_class
  const problems: string[] = []
  if (!draft.name.trim()) problems.push('nome obrigatório')
  if (tickerRequired && !draft.ticker.trim()) problems.push('ticker obrigatório pra esta classe')
  if (tickerForbidden && draft.ticker.trim() && tickerTouched) problems.push('esta classe não usa ticker')
  if (draft.cnpj.trim() && draft.asset_class !== 'FUND' && cnpjTouched) problems.push('CNPJ só em fundos')
  if (draft.fiId !== asset.financial_institution_id && accounts && !resolvedAccount) {
    problems.push('custodiante sem conta de investimento no workspace')
  }
  if (classChangedToDetails) problems.push('mudar pra renda fixa/imóvel/veículo exige detalhes — use "Formulário completo…"')
  const canSave = editing && dirty && problems.length === 0 && !saving

  async function save() {
    if (!canSave) return
    setSaving(true)
    try {
      const updated = await api.patchAsset(asset.id, patch)
      onSaved(updated)
      setEditing(false)
    } catch (e) {
      onError(e instanceof Error ? e.message : 'Erro ao salvar o ativo')
    } finally {
      setSaving(false)
    }
  }

  const klass = collapsedOf(asset.asset_class)
  const sel = `${INPUT_CLS} appearance-none`

  return (
    <Card>
      <SectionTitle action={
        editing ? (
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setEditing(false)}
              disabled={saving}
              className="h-7 px-2.5 rounded-md text-[11px] bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700 disabled:opacity-50"
            >
              Cancelar
            </button>
            <button
              type="button"
              onClick={() => void save()}
              disabled={!canSave}
              data-testid="asset-data-save"
              title={problems[0]}
              className="h-7 px-2.5 inline-flex items-center gap-1 rounded-md text-[11px] font-medium bg-indigo-500 hover:bg-indigo-400 text-white disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {saving && <Loader2 className="w-3 h-3 animate-spin" />}
              {saving ? 'Salvando…' : 'Salvar'}
            </button>
          </div>
        ) : (
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onEditDetails}
              data-testid="asset-data-full-form"
              title={NEEDS_DETAILS.includes(asset.asset_class)
                ? 'Editar vencimento, indexador, taxa (ou endereço/placa) no formulário completo'
                : 'Formulário completo — inclusive pra converter em renda fixa, imóvel ou veículo'}
              className="h-7 px-2.5 rounded-md text-[11px] bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700"
            >
              {NEEDS_DETAILS.includes(asset.asset_class) ? 'Editar detalhes…' : 'Formulário completo…'}
            </button>
            <button
              type="button"
              onClick={startEditing}
              data-testid="asset-data-edit"
              className="h-7 px-2.5 inline-flex items-center gap-1 rounded-md text-[11px] bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700"
            >
              <Edit2 className="w-3 h-3" /> Editar
            </button>
          </div>
        )
      }>
        Dados do ativo
      </SectionTitle>

      {editing ? (
        <form
          className="grid grid-cols-2 lg:grid-cols-4 gap-x-4 gap-y-3 text-[12px]"
          onSubmit={e => { e.preventDefault(); void save() }}
          data-testid="asset-data-form"
        >
          <label className="col-span-2 grid gap-1">
            <span className="text-[10px] uppercase tracking-wider text-gray-500">Nome</span>
            <input className={INPUT_CLS} value={draft.name} onChange={e => setDraft({ ...draft, name: e.target.value })} data-testid="asset-data-name" />
          </label>
          <label className="grid gap-1">
            <span className="text-[10px] uppercase tracking-wider text-gray-500">Ticker{tickerRequired ? ' *' : ''}</span>
            <input className={`${INPUT_CLS} font-mono`} value={draft.ticker} disabled={tickerForbidden}
              onChange={e => setDraft({ ...draft, ticker: e.target.value.toUpperCase() })} data-testid="asset-data-ticker" />
          </label>
          <label className="grid gap-1">
            <span className="text-[10px] uppercase tracking-wider text-gray-500">CNPJ</span>
            <input className={`${INPUT_CLS} font-mono`} value={draft.cnpj} disabled={draft.asset_class !== 'FUND'}
              onChange={e => setDraft({ ...draft, cnpj: e.target.value })} data-testid="asset-data-cnpj" />
          </label>
          <label className="grid gap-1">
            <span className="text-[10px] uppercase tracking-wider text-gray-500">Classe</span>
            <select
              className={sel}
              value={draft.asset_class}
              onChange={e => {
                const c = e.target.value as AssetClass
                setDraft({
                  ...draft,
                  asset_class: c,
                  ticker: TICKER_FORBIDDEN.includes(c) ? '' : draft.ticker,
                  cnpj: c === 'FUND' ? draft.cnpj : '',
                })
              }}
              data-testid="asset-data-class"
            >
              {(Object.keys(CLASS_LABELS) as AssetClass[]).map(c => <option key={c} value={c}>{CLASS_LABELS[c]}</option>)}
            </select>
          </label>
          <label className="grid gap-1">
            <span className="text-[10px] uppercase tracking-wider text-gray-500">País</span>
            <select className={sel} value={draft.country} onChange={e => setDraft({ ...draft, country: e.target.value })}>
              <option value="BR">🇧🇷 Brasil</option>
              <option value="US">🇺🇸 EUA</option>
            </select>
          </label>
          <label className="grid gap-1">
            <span className="text-[10px] uppercase tracking-wider text-gray-500">Moeda</span>
            <select className={sel} value={draft.currency} onChange={e => setDraft({ ...draft, currency: e.target.value as 'BRL' | 'USD' })}>
              <option value="BRL">BRL</option>
              <option value="USD">USD</option>
            </select>
          </label>
          <label className="grid gap-1">
            <span className="text-[10px] uppercase tracking-wider text-gray-500">Custodiante</span>
            <select className={sel} value={draft.fiId} onChange={e => setDraft({ ...draft, fiId: e.target.value })} data-testid="asset-data-fi">
              {institutions.map(f => <option key={f.id} value={f.id}>{f.short_name}</option>)}
            </select>
            <span className="text-[10px] text-gray-500 truncate">
              {accounts == null && draft.fiId !== asset.financial_institution_id
                ? 'carregando contas…'
                : resolvedAccount ? `conta: ${resolvedAccount.name}` : 'sem conta de investimento nesse custodiante'}
            </span>
          </label>
          {problems.length > 0 && dirty && (
            <div className="col-span-2 lg:col-span-4 text-[11px] text-amber-600 dark:text-amber-400" data-testid="asset-data-problems">
              {problems.join(' · ')}
            </div>
          )}
        </form>
      ) : (
        <dl className="grid grid-cols-2 lg:grid-cols-4 gap-x-6 gap-y-3 text-[12px]">
          <Detail label="Nome" value={asset.name} />
          <Detail label="Ticker" value={asset.ticker || '—'} mono />
          <Detail label="CNPJ" value={asset.cnpj || '—'} mono />
          <Detail label="Classe">
            <ClassBadge klass={klass} size="xs" withDot={false} />
          </Detail>
          <Detail label="País">
            <span className="inline-flex items-center gap-1.5">
              <CountryFlag country={asset.country} />
              <span>{asset.country === 'BR' ? 'Brasil' : asset.country === 'US' ? 'EUA' : asset.country}</span>
            </span>
          </Detail>
          <Detail label="Moeda"><CcyPill ccy={asset.currency} /></Detail>
          <Detail label="Custodiante" value={fi?.short_name || '—'} />
          <Detail label="Conta" value={account?.name || '—'} />
          <Detail label="Status">
            {asset.is_active
              ? <span className="text-emerald-500 dark:text-emerald-400">Ativo</span>
              : <span className="text-gray-500">Zerado</span>}
          </Detail>
          <Detail label="Total investido" value={fmtBRL(costBRL, { compact: true })} tnum money />
          <Detail label="Total recebido" value={fmtBRL(receivedBRL, { compact: true })} tnum money tone="positive" />
          <Detail label="Lançamentos" value={String(movementsCount)} tnum />
          <Detail label="Último lançamento" value={lastMovementDate ? fmtDate(lastMovementDate) : '—'} tnum />
          <Detail label="Criado em" value={fmtDate(asset.created_at)} tnum />
          <Detail label="Atualizado em" value={fmtDate(asset.updated_at)} tnum />
          {asset.external_source && (
            <Detail label="Origem" value={`${asset.external_source}${asset.external_id ? ` · ${asset.external_id}` : ''}`} mono />
          )}
        </dl>
      )}

      {canDeactivate && asset.is_active && !editing && (
        <div className="mt-4 pt-3 border-t border-gray-100 dark:border-gray-800 flex items-center justify-between text-[11px] text-gray-500">
          <span>Zerar o ativo o tira das listas e dos próximos fechamentos. Lançamentos e histórico ficam.</span>
          <button
            type="button"
            onClick={onDeactivate}
            data-testid="asset-data-deactivate"
            className="h-7 px-2.5 rounded-md text-[11px] text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20"
          >
            Zerar ativo
          </button>
        </div>
      )}
    </Card>
  )
}
