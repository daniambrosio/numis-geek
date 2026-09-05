/* Spec 81 — barra de abas da página do ativo. Genérica: ids em EN (vão pra
 * URL em `?tab=`), labels em PT, contagem opcional. */

export interface AssetTabDef<T extends string = string> {
  id: T
  label: string
  count?: number
}

interface Props<T extends string> {
  tabs: AssetTabDef<T>[]
  value: T
  onChange: (id: T) => void
}

export default function AssetTabs<T extends string>({ tabs, value, onChange }: Props<T>) {
  return (
    <div
      role="tablist"
      aria-label="Seções do ativo"
      className="flex items-end gap-1 border-b border-gray-200 dark:border-gray-800 overflow-x-auto"
    >
      {tabs.map(t => {
        const active = t.id === value
        return (
          <button
            key={t.id}
            role="tab"
            type="button"
            aria-selected={active}
            data-testid={`asset-tab-${t.id}`}
            onClick={() => onChange(t.id)}
            className={`-mb-px px-3 py-2 inline-flex items-center gap-1.5 text-[12px] font-medium border-b-2 transition-colors whitespace-nowrap ${
              active
                ? 'border-indigo-500 text-gray-900 dark:text-white'
                : 'border-transparent text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'
            }`}
          >
            {t.label}
            {t.count != null && (
              <span className={`tnum text-[10px] px-1.5 py-0.5 rounded-full ${
                active
                  ? 'bg-indigo-500/15 text-indigo-600 dark:text-indigo-300'
                  : 'bg-gray-100 dark:bg-gray-800 text-gray-500'
              }`}>
                {t.count}
              </span>
            )}
          </button>
        )
      })}
    </div>
  )
}
