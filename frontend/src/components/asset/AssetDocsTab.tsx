/* Spec 81 — aba "Documentos & dados". Fase 3: o card Detalhes (read-only).
 * Fase 6 troca por AssetDataCard (edição inline) + NotesAttachmentsCard. */
import type { ReactNode } from 'react'

import type { AccountOut, AssetOut, FinancialInstitutionOut } from '../../lib/api'
import { fmtDate } from '../../lib/format'
import { fmtBRL } from '../../lib/money'
import { collapsedOf } from '../../lib/tokens'
import { Card, CcyPill, ClassBadge, SectionTitle } from '../ui'
import CountryFlag from './CountryFlag'

interface Props {
  asset: AssetOut
  fi: FinancialInstitutionOut | null
  account: AccountOut | null
  costBRL: number | null
  receivedBRL: number
  movementsCount: number
  lastMovementDate?: string
}

export default function AssetDocsTab({
  asset, fi, account, costBRL, receivedBRL, movementsCount, lastMovementDate,
}: Props) {
  const klass = collapsedOf(asset.asset_class)
  return (
    <div className="space-y-6" data-testid="asset-tab-panel-docs">
      <Card>
        <SectionTitle>Detalhes</SectionTitle>
        <dl className="grid grid-cols-2 lg:grid-cols-4 gap-x-6 gap-y-3 text-[12px]">
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
          <Detail label="Moeda">
            <CcyPill ccy={asset.currency} />
          </Detail>
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
        </dl>
      </Card>
    </div>
  )
}

export function Detail({
  label, value, children, mono, tnum, money, tone,
}: {
  label: string
  value?: string
  children?: ReactNode
  mono?: boolean
  tnum?: boolean
  money?: boolean
  tone?: 'positive' | 'negative'
}) {
  const toneCls = tone === 'positive' ? 'text-emerald-500 dark:text-emerald-400'
    : tone === 'negative' ? 'text-red-500 dark:text-red-400'
    : 'text-gray-900 dark:text-white'
  const cls = `mt-0.5 ${mono ? 'font-mono' : ''} ${tnum ? 'tnum' : ''} ${money ? 'money' : ''} ${toneCls}`.trim()
  return (
    <div>
      <dt className="text-[10px] uppercase tracking-wider text-gray-500 dark:text-gray-400">{label}</dt>
      <dd className={cls}>{children ?? value}</dd>
    </div>
  )
}
