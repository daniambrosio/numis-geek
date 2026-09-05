/* Spec 81 — aba "Documentos & dados": card de dados com edição inline e
 * notas + anexos do ativo (NotesAttachmentsCard com sourceType='asset'). */
import type { ReactNode } from 'react'

import type {
  AccountOut, AssetOut, AttachmentOut, FinancialInstitutionOut,
} from '../../lib/api'
import NotesAttachmentsCard from '../NotesAttachmentsCard'
import AssetDataCard from './AssetDataCard'

interface Props {
  asset: AssetOut
  fi: FinancialInstitutionOut | null
  account: AccountOut | null
  institutions: FinancialInstitutionOut[]
  canDeactivate: boolean
  costBRL: number | null
  receivedBRL: number
  movementsCount: number
  lastMovementDate?: string
  autoEdit?: boolean
  onAutoEditConsumed?: () => void
  onSaved: (asset: AssetOut) => void
  onError: (msg: string) => void
  onEditDetails: () => void
  onDeactivate: () => void
  attachments: AttachmentOut[]
  onAttachmentsChanged: () => void | Promise<void>
  onNotesSave: (notes: string) => Promise<void>
}

export default function AssetDocsTab({
  asset, fi, account, institutions, canDeactivate,
  costBRL, receivedBRL, movementsCount, lastMovementDate,
  autoEdit, onAutoEditConsumed, onSaved, onError, onEditDetails, onDeactivate,
  attachments, onAttachmentsChanged, onNotesSave,
}: Props) {
  return (
    <div className="space-y-6" data-testid="asset-tab-panel-docs">
      <AssetDataCard
        asset={asset}
        fi={fi}
        account={account}
        institutions={institutions}
        canDeactivate={canDeactivate}
        costBRL={costBRL}
        receivedBRL={receivedBRL}
        movementsCount={movementsCount}
        lastMovementDate={lastMovementDate}
        autoEdit={autoEdit}
        onAutoEditConsumed={onAutoEditConsumed}
        onSaved={onSaved}
        onError={onError}
        onEditDetails={onEditDetails}
        onDeactivate={onDeactivate}
      />
      <NotesAttachmentsCard
        notes={asset.notes ?? ''}
        onNotesSave={onNotesSave}
        sourceType="asset"
        sourceId={asset.id}
        attachments={attachments}
        onAttachmentsChanged={onAttachmentsChanged}
        label="Notas & documentos do ativo"
      />
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
