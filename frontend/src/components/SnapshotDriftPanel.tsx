/* Spec 51 Bloco 3 — painel "Divergências aceitas" no SnapshotDetail.
 *
 * Lista entradas onde o usuário viu o impacto de um evento retroativo
 * e optou por "Manter divergência" (audit log
 * action='snapshot.recompute.skipped'). Cada entrada vira uma linha
 * compacta com asset, motivo e timestamp. Útil pra auditoria e pra
 * lembrar o que foi conscientemente deixado fora de sync. */
import { AlertTriangle } from 'lucide-react'
import { Link } from 'react-router-dom'

import type { DriftEntryOut } from '../lib/api'
import { Card, SectionTitle } from './ui'

interface Props {
  drift: DriftEntryOut[]
}

function fmtDateTime(iso: string): string {
  if (!iso) return ''
  try {
    return new Date(iso).toLocaleString('pt-BR', {
      day: '2-digit', month: '2-digit', year: '2-digit',
      hour: '2-digit', minute: '2-digit',
    })
  } catch {
    return iso
  }
}

const EVENT_LABEL: Record<string, string> = {
  'asset_movement.create':   'Lançamento criado',
  'asset_movement.update':   'Lançamento editado',
  'corporate_action.create': 'Corporate action',
}

export default function SnapshotDriftPanel({ drift }: Props) {
  if (drift.length === 0) return null

  return (
    <Card padding="p-5">
      <div className="flex items-center justify-between mb-3">
        <SectionTitle>
          <span className="inline-flex items-center gap-2">
            <AlertTriangle className="w-4 h-4 text-amber-500" />
            Divergências aceitas
          </span>
        </SectionTitle>
        <span className="text-[10px] text-gray-500">
          {drift.length} entrada{drift.length === 1 ? '' : 's'}
        </span>
      </div>
      <div className="text-[11px] text-gray-500 dark:text-gray-400 mb-3">
        O usuário optou conscientemente por <strong>não recomputar</strong> estes
        ativos quando um evento retroativo foi detectado. O snapshot
        permanece divergente da realidade atual desses ativos.
      </div>
      <div className="space-y-2" data-testid="snapshot-drift-panel">
        {drift.map((d, i) => (
          <div
            key={`${d.asset_id}-${i}`}
            className="rounded-lg border border-amber-200 dark:border-amber-900/40 bg-amber-50/50 dark:bg-amber-900/10 p-3"
          >
            <div className="flex items-center justify-between gap-2">
              <div className="min-w-0">
                {d.asset_id ? (
                  <Link
                    to={`/assets/${d.asset_id}`}
                    className="text-[12px] font-semibold text-indigo-500 hover:text-indigo-300"
                  >
                    {d.asset_ticker || d.asset_name || d.asset_id}
                  </Link>
                ) : (
                  <span className="text-[12px] font-semibold text-gray-700 dark:text-gray-300">
                    (ativo removido)
                  </span>
                )}
                {d.asset_name && d.asset_ticker && (
                  <span className="ml-1 text-[10px] text-gray-500">
                    · {d.asset_name}
                  </span>
                )}
              </div>
              <div className="text-[10px] text-gray-500">
                {fmtDateTime(d.created_at)}
              </div>
            </div>
            <div className="mt-1 text-[11px] text-gray-700 dark:text-gray-300">
              {d.reason}
            </div>
            <div className="mt-1 text-[10px] text-gray-500 flex items-center gap-2">
              <span>
                Trigger:{' '}
                <span className="text-gray-700 dark:text-gray-300">
                  {EVENT_LABEL[d.trigger_event_type] ?? d.trigger_event_type}
                </span>
              </span>
              <span>·</span>
              <span>por {d.user_email}</span>
            </div>
          </div>
        ))}
      </div>
    </Card>
  )
}
