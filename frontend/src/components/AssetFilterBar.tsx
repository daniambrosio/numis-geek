/* Filtro reutilizável pra listas de ativos.
 *
 * Sessão 2026-06-06: extraído da página /ativos pra ser usado também no
 * snapshot Posições Congeladas e em qualquer outro lugar que precise
 * dos mesmos filtros (Classe / País / Custodiante + busca + grouping +
 * include-zeroed toggle).
 *
 * Componente é CONTROLADO — caller mantém o state e aplica a filtragem.
 * O componente só pinta a UI + dispara onChange. Por quê:
 *  - Cada caller pode persistir/aplicar do seu jeito (querystring, etc).
 *  - A semântica de "zerados" muda entre páginas (em Ativos = inativo,
 *    em snapshot = sem market_value). Caller é dono da regra.
 *  - O FILTERING propriamente dito muda o shape do data (AssetOut[] vs
 *    SnapshotItemOut[]). Componente fica neutro.
 *
 * Features opcionais (escondem quando prop é undefined):
 *  - Toggle "Incluir zerados"
 *  - Grouping (linha Agrupar por)
 *  - Slot countSlot pro lado direito da linha de grouping
 */
import { type ReactNode } from 'react'

import {
  Card, FilterGroup, GroupingToggle, MultiChips, SearchInput, ToggleSwitch,
} from './ui'
import { KLASS, type CollapsedClassCode } from '../lib/tokens'

export const KLASS_OPTS = (Object.keys(KLASS) as CollapsedClassCode[]).map(id => ({
  id,
  label: KLASS[id].label,
  color: KLASS[id].color,
}))

export const COUNTRY_OPTS = [
  { id: 'BR', label: '🇧🇷 Brasil' },
  { id: 'US', label: '🇺🇸 EUA' },
]

interface FiOption { id: string; label: string; color: string }

interface Props {
  // Busca
  search: string
  onSearchChange: (v: string) => void
  searchPlaceholder?: string

  // Classe (collapsed)
  klassSel: string[]
  onKlassChange: (v: string[]) => void

  // País (BR/US)
  countrySel: string[]
  onCountryChange: (v: string[]) => void

  // Custodiante — caller decide quais FIs aparecem (e.g., só as presentes
  // nos ativos atuais).
  fiOpts: FiOption[]
  fiSel: string[]
  onFiChange: (v: string[]) => void

  // Toggle "Incluir zerados" (esconde se onIncludeZeroedChange undefined).
  includeZeroed?: boolean
  onIncludeZeroedChange?: (v: boolean) => void
  includeZeroedLabel?: string

  // Linha de grouping (esconde se groupingOpts undefined).
  grouping?: string
  onGroupingChange?: (v: string) => void
  groupingOpts?: { id: string; label: string }[]

  // Slot do lado direito da linha de grouping (default: nada). Caller passa
  // algo como "150 de 154 ativos".
  countSlot?: ReactNode
}

export default function AssetFilterBar({
  search, onSearchChange, searchPlaceholder = 'Buscar por ticker ou nome…',
  klassSel, onKlassChange,
  countrySel, onCountryChange,
  fiOpts, fiSel, onFiChange,
  includeZeroed, onIncludeZeroedChange, includeZeroedLabel = 'Incluir zerados',
  grouping, onGroupingChange, groupingOpts,
  countSlot,
}: Props) {
  const hasGroupingRow = groupingOpts && onGroupingChange
  return (
    <Card padding="p-3" className="space-y-3">
      <div className="flex items-center gap-3 flex-wrap">
        <SearchInput
          value={search}
          onChange={onSearchChange}
          placeholder={searchPlaceholder}
          className="w-64"
        />
        <div className="flex-1" />
        {onIncludeZeroedChange && (
          <ToggleSwitch
            on={includeZeroed ?? false}
            onChange={onIncludeZeroedChange}
            label={includeZeroedLabel}
          />
        )}
      </div>
      <div className="space-y-2 pt-3 border-t border-gray-200 dark:border-gray-800">
        <FilterGroup label="Classe">
          <MultiChips options={KLASS_OPTS} selected={klassSel} onChange={onKlassChange} />
        </FilterGroup>
        <FilterGroup label="País">
          <MultiChips options={COUNTRY_OPTS} selected={countrySel} onChange={onCountryChange} />
        </FilterGroup>
        <FilterGroup label="Custodiante">
          <MultiChips options={fiOpts} selected={fiSel} onChange={onFiChange} />
        </FilterGroup>
      </div>
      {hasGroupingRow && (
        <div className="flex items-center gap-3 pt-3 border-t border-gray-200 dark:border-gray-800 flex-wrap">
          <span className="text-[10px] uppercase tracking-wider text-gray-500 dark:text-gray-400 font-medium min-w-[90px]">
            Agrupar por
          </span>
          <GroupingToggle
            value={grouping ?? 'none'}
            onChange={onGroupingChange!}
            options={groupingOpts!}
          />
          <div className="flex-1" />
          {countSlot && (
            <div className="text-[11px] text-gray-500 dark:text-gray-400">{countSlot}</div>
          )}
        </div>
      )}
    </Card>
  )
}
