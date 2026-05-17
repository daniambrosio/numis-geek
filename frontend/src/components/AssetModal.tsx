import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type AssetClass, type AssetOut, type AssetRequest, type FinancialInstitutionOut, type FixedIncomeDetails, type FixedIncomeIndexer, type AssetMovementOut, type PhysicalDetails, type PositionOut } from '../lib/api'

const CLASS_LABELS: Record<AssetClass, string> = {
  STOCK: 'Ação',
  REIT: 'FII / REIT',
  ETF: 'ETF',
  FIXED_INCOME: 'Renda Fixa',
  FUND: 'Fundo',
  CRYPTO: 'Cripto',
  REAL_ESTATE: 'Imóvel',
  VEHICLE: 'Veículo',
  CASH: 'Dinheiro',
  FGTS: 'FGTS',
  PRIVATE_PENSION: 'Previdência',
}

// PRIVATE_PENSION/FGTS/CASH behave like ticker classes but ticker is optional
// (per spec 07a — Notion has no ticker for those rows).
const TICKER_REQUIRED: AssetClass[] = ['STOCK', 'ETF', 'REIT', 'CRYPTO']
const TICKER_FORBIDDEN: AssetClass[] = ['FIXED_INCOME', 'REAL_ESTATE', 'VEHICLE']
const NEEDS_FIXED_INCOME: AssetClass[] = ['FIXED_INCOME']
const NEEDS_PHYSICAL: AssetClass[] = ['REAL_ESTATE', 'VEHICLE']

const INDEXERS: FixedIncomeIndexer[] = ['CDI', 'IPCA', 'SELIC', 'PREFIXED', 'USD']

interface Props {
  initial?: AssetOut
  institutions: FinancialInstitutionOut[]
  /** Forced workspace (used by sysadmin when a specific workspace is selected). */
  forcedWorkspaceId?: string
  /** Workspace selector source (sysadmin only — when no workspace is forced). */
  workspaceOptions?: { id: string; name: string }[]
  onSave: (data: AssetRequest) => Promise<void>
  onClose: () => void
}

export default function AssetModal({ initial, institutions, forcedWorkspaceId, workspaceOptions, onSave, onClose }: Props) {
  const initialDetails = initial?.details ?? null
  const initialFi = initialDetails as FixedIncomeDetails | null
  const initialPhysical = initialDetails as PhysicalDetails | null
  const isFiClass = initial && NEEDS_FIXED_INCOME.includes(initial.asset_class)
  const isPhysicalClass = initial && NEEDS_PHYSICAL.includes(initial.asset_class)

  const [assetClass, setAssetClass] = useState<AssetClass>(initial?.asset_class ?? 'STOCK')
  const [country, setCountry] = useState<string>(initial?.country ?? 'BR')
  const [name, setName] = useState(initial?.name ?? '')
  const [fiId, setFiId] = useState(initial?.financial_institution_id ?? (institutions[0]?.id ?? ''))
  const [currency, setCurrency] = useState<'BRL' | 'USD'>(initial?.currency ?? 'BRL')
  const [ticker, setTicker] = useState(initial?.ticker ?? '')
  const [cnpj, setCnpj] = useState(initial?.cnpj ?? '')
  const [currentPrice, setCurrentPrice] = useState<string>(initial?.current_price != null ? String(initial.current_price) : '')
  const [notes, setNotes] = useState(initial?.notes ?? '')
  const [workspaceId, setWorkspaceId] = useState(
    initial?.workspace_id
      ?? forcedWorkspaceId
      ?? workspaceOptions?.[0]?.id
      ?? ''
  )

  // Fixed-income fields
  const [fiIssuer, setFiIssuer] = useState(isFiClass ? initialFi?.issuer ?? '' : '')
  const [fiIssueDate, setFiIssueDate] = useState(isFiClass ? initialFi?.issue_date ?? '' : '')
  const [fiMaturityDate, setFiMaturityDate] = useState(isFiClass ? initialFi?.maturity_date ?? '' : '')
  const [fiIndexer, setFiIndexer] = useState<FixedIncomeIndexer>(isFiClass ? initialFi?.indexer ?? 'CDI' : 'CDI')
  const [fiRate, setFiRate] = useState(isFiClass && initialFi?.rate != null ? String(initialFi.rate) : '')
  const [fiFaceValue, setFiFaceValue] = useState(isFiClass && initialFi?.face_value != null ? String(initialFi.face_value) : '')

  // Physical fields
  const [phAddress, setPhAddress] = useState(isPhysicalClass ? initialPhysical?.address ?? '' : '')
  const [phCity, setPhCity] = useState(isPhysicalClass ? initialPhysical?.city ?? '' : '')
  const [phState, setPhState] = useState(isPhysicalClass ? initialPhysical?.state ?? '' : '')
  const [phCountry, setPhCountry] = useState(isPhysicalClass ? initialPhysical?.country ?? 'BR' : 'BR')
  const [phAreaM2, setPhAreaM2] = useState(isPhysicalClass && initialPhysical?.area_m2 != null ? String(initialPhysical.area_m2) : '')
  const [phRegistration, setPhRegistration] = useState(isPhysicalClass ? initialPhysical?.registration_number ?? '' : '')
  const [phMake, setPhMake] = useState(isPhysicalClass ? initialPhysical?.make ?? '' : '')
  const [phModel, setPhModel] = useState(isPhysicalClass ? initialPhysical?.model ?? '' : '')
  const [phYear, setPhYear] = useState(isPhysicalClass && initialPhysical?.year != null ? String(initialPhysical.year) : '')
  const [phLicensePlate, setPhLicensePlate] = useState(isPhysicalClass ? initialPhysical?.license_plate ?? '' : '')
  const [phChassis, setPhChassis] = useState(isPhysicalClass ? initialPhysical?.chassis ?? '' : '')

  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  // Position + recent lançamentos (only when editing an existing asset).
  const [position, setPosition] = useState<PositionOut | null>(null)
  const [recentLans, setRecentLans] = useState<AssetMovementOut[]>([])
  const [posLoading, setPosLoading] = useState(false)
  useEffect(() => {
    if (!initial) return
    setPosLoading(true)
    Promise.all([
      api.getAssetPosition(initial.id),
      api.listAssetMovementsForAsset(initial.id, { page_size: 5 }),
    ])
      .then(([p, l]) => { setPosition(p); setRecentLans(l.items) })
      .catch(() => { /* keep panel quiet on errors */ })
      .finally(() => setPosLoading(false))
  }, [initial])

  const tickerRequired = TICKER_REQUIRED.includes(assetClass)
  const tickerForbidden = TICKER_FORBIDDEN.includes(assetClass)
  const isFund = assetClass === 'FUND'
  const showFixedIncome = NEEDS_FIXED_INCOME.includes(assetClass)
  const showPhysical = NEEDS_PHYSICAL.includes(assetClass)
  const isRealEstate = assetClass === 'REAL_ESTATE'
  const isVehicle = assetClass === 'VEHICLE'

  // Workspace picker only for create + sysadmin without a forced workspace
  const showWorkspacePicker = !initial && !forcedWorkspaceId && workspaceOptions && workspaceOptions.length > 0

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    setSaving(true)
    try {
      const payload: AssetRequest = {
        asset_class: assetClass,
        country: country.toUpperCase(),
        financial_institution_id: fiId,
        name: name.trim(),
        currency,
        ticker: tickerForbidden ? null : (ticker.trim() || null),
        cnpj: isFund ? (cnpj.trim() || null) : null,
        current_price: currentPrice.trim() === '' ? null : parseFloat(currentPrice),
        notes: notes.trim() || null,
      }
      if (showWorkspacePicker && workspaceId) {
        payload.workspace_id = workspaceId
      } else if (forcedWorkspaceId) {
        payload.workspace_id = forcedWorkspaceId
      }
      if (showFixedIncome) {
        payload.details = {
          issuer: fiIssuer.trim(),
          issue_date: fiIssueDate || null,
          maturity_date: fiMaturityDate,
          indexer: fiIndexer,
          rate: fiRate === '' ? null : parseFloat(fiRate),
          face_value: fiFaceValue === '' ? null : parseFloat(fiFaceValue),
        }
      } else if (showPhysical) {
        payload.details = {
          address: phAddress.trim() || null,
          city: phCity.trim() || null,
          state: phState.trim() || null,
          country: phCountry.trim() || null,
          area_m2: phAreaM2 === '' ? null : parseFloat(phAreaM2),
          registration_number: phRegistration.trim() || null,
          make: phMake.trim() || null,
          model: phModel.trim() || null,
          year: phYear === '' ? null : parseInt(phYear, 10),
          license_plate: phLicensePlate.trim() || null,
          chassis: phChassis.trim() || null,
        }
      }
      await onSave(payload)
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Erro ao salvar.')
    } finally {
      setSaving(false)
    }
  }

  const externalSourceLabel = (() => {
    if (!initial?.external_source) return null
    switch (initial.external_source) {
      case 'NOTION': return 'Notion'
      case 'B3': return 'B3'
      case 'BROKER_NOTE': return 'Nota de Corretagem'
      case 'MANUAL_CSV': return 'CSV manual'
      default: return initial.external_source
    }
  })()

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="w-full max-w-lg max-h-[90vh] overflow-y-auto bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-700 shadow-xl p-6">
        <div className="flex items-center justify-between mb-5">
          <h2 className="text-base font-semibold text-gray-900 dark:text-white">
            {initial ? 'Editar Ativo' : 'Novo Ativo'}
          </h2>
          {externalSourceLabel && (
            <span
              className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400 border border-gray-200 dark:border-gray-700"
              title={initial?.external_id || ''}
            >
              Origem: {externalSourceLabel}
            </span>
          )}
        </div>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm text-gray-700 dark:text-gray-300 mb-1">Classe</label>
            <select
              value={assetClass}
              onChange={e => setAssetClass(e.target.value as AssetClass)}
              disabled={!!initial}
              className="w-full px-3.5 py-2 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 disabled:opacity-60"
            >
              {(Object.keys(CLASS_LABELS) as AssetClass[]).map(c => (
                <option key={c} value={c}>{CLASS_LABELS[c]}</option>
              ))}
            </select>
          </div>

          {showWorkspacePicker && (
            <div>
              <label className="block text-sm text-gray-700 dark:text-gray-300 mb-1">Workspace</label>
              <select
                value={workspaceId}
                onChange={e => setWorkspaceId(e.target.value)}
                required
                className="w-full px-3.5 py-2 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
              >
                {workspaceOptions!.map(w => (
                  <option key={w.id} value={w.id}>{w.name}</option>
                ))}
              </select>
            </div>
          )}

          <div>
            <label className="block text-sm text-gray-700 dark:text-gray-300 mb-1">Custodiante (Instituição Financeira)</label>
            <select
              value={fiId}
              onChange={e => setFiId(e.target.value)}
              required
              className="w-full px-3.5 py-2 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
            >
              {institutions.map(fi => (
                <option key={fi.id} value={fi.id}>{fi.short_name}</option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-sm text-gray-700 dark:text-gray-300 mb-1">Nome</label>
            <input
              type="text"
              value={name}
              onChange={e => setName(e.target.value)}
              required
              placeholder="Ex: Petrobras PN"
              className="w-full px-3.5 py-2 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
          </div>

          <div className="grid grid-cols-3 gap-3">
            <div>
              <label className="block text-sm text-gray-700 dark:text-gray-300 mb-1">Moeda</label>
              <select
                value={currency}
                onChange={e => setCurrency(e.target.value as 'BRL' | 'USD')}
                className="w-full px-3.5 py-2 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
              >
                <option value="BRL">BRL</option>
                <option value="USD">USD</option>
              </select>
            </div>
            <div>
              <label className="block text-sm text-gray-700 dark:text-gray-300 mb-1">País</label>
              <select
                value={country}
                onChange={e => setCountry(e.target.value)}
                className="w-full px-3.5 py-2 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
              >
                <option value="BR">🇧🇷 Brasil</option>
                <option value="US">🇺🇸 EUA</option>
              </select>
            </div>
            <div>
              <label className="block text-sm text-gray-700 dark:text-gray-300 mb-1">
                Preço atual <span className="text-xs text-gray-400">(opcional)</span>
              </label>
              <input
                type="number"
                step="0.01"
                value={currentPrice}
                onChange={e => setCurrentPrice(e.target.value)}
                placeholder="0,00"
                className="w-full px-3.5 py-2 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
              />
            </div>
          </div>

          {!tickerForbidden && (
            <div>
              <label className="block text-sm text-gray-700 dark:text-gray-300 mb-1">
                Ticker {tickerRequired && <span className="text-red-500">*</span>}
                {!tickerRequired && !isFund && <span className="text-xs text-gray-400"> (opcional)</span>}
                {isFund && <span className="text-xs text-gray-400"> (opcional)</span>}
              </label>
              <input
                type="text"
                value={ticker}
                onChange={e => setTicker(e.target.value.toUpperCase())}
                required={tickerRequired}
                placeholder="Ex: PETR4"
                className="w-full px-3.5 py-2 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
              />
            </div>
          )}

          {isFund && (
            <div>
              <label className="block text-sm text-gray-700 dark:text-gray-300 mb-1">CNPJ</label>
              <input
                type="text"
                value={cnpj}
                onChange={e => setCnpj(e.target.value)}
                placeholder="00.000.000/0001-00"
                className="w-full px-3.5 py-2 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
              />
            </div>
          )}

          {showFixedIncome && (
            <div className="border-t border-gray-200 dark:border-gray-700 pt-4 space-y-3">
              <div>
                <label className="block text-sm text-gray-700 dark:text-gray-300 mb-1">Emissor</label>
                <input
                  type="text"
                  value={fiIssuer}
                  onChange={e => setFiIssuer(e.target.value)}
                  required
                  placeholder="Ex: Banco BTG Pactual"
                  className="w-full px-3.5 py-2 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-sm text-gray-700 dark:text-gray-300 mb-1">Data de emissão</label>
                  <input
                    type="date"
                    value={fiIssueDate}
                    onChange={e => setFiIssueDate(e.target.value)}
                    className="w-full px-3.5 py-2 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  />
                </div>
                <div>
                  <label className="block text-sm text-gray-700 dark:text-gray-300 mb-1">Vencimento</label>
                  <input
                    type="date"
                    value={fiMaturityDate}
                    onChange={e => setFiMaturityDate(e.target.value)}
                    required
                    className="w-full px-3.5 py-2 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  />
                </div>
              </div>
              <div className="grid grid-cols-3 gap-3">
                <div>
                  <label className="block text-sm text-gray-700 dark:text-gray-300 mb-1">Indexador</label>
                  <select
                    value={fiIndexer}
                    onChange={e => setFiIndexer(e.target.value as FixedIncomeIndexer)}
                    className="w-full px-3.5 py-2 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  >
                    {INDEXERS.map(i => <option key={i} value={i}>{i}</option>)}
                  </select>
                </div>
                <div>
                  <label className="block text-sm text-gray-700 dark:text-gray-300 mb-1">Taxa</label>
                  <input
                    type="number"
                    step="0.0001"
                    value={fiRate}
                    onChange={e => setFiRate(e.target.value)}
                    required
                    placeholder="110.0"
                    className="w-full px-3.5 py-2 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  />
                </div>
                <div>
                  <label className="block text-sm text-gray-700 dark:text-gray-300 mb-1">Valor nominal</label>
                  <input
                    type="number"
                    step="0.01"
                    value={fiFaceValue}
                    onChange={e => setFiFaceValue(e.target.value)}
                    placeholder="(opcional)"
                    className="w-full px-3.5 py-2 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  />
                </div>
              </div>
            </div>
          )}

          {isRealEstate && (
            <div className="border-t border-gray-200 dark:border-gray-700 pt-4 space-y-3">
              <div>
                <label className="block text-sm text-gray-700 dark:text-gray-300 mb-1">Endereço</label>
                <input
                  type="text"
                  value={phAddress}
                  onChange={e => setPhAddress(e.target.value)}
                  required
                  className="w-full px-3.5 py-2 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                />
              </div>
              <div className="grid grid-cols-3 gap-3">
                <div>
                  <label className="block text-sm text-gray-700 dark:text-gray-300 mb-1">Cidade</label>
                  <input
                    type="text"
                    value={phCity}
                    onChange={e => setPhCity(e.target.value)}
                    required
                    className="w-full px-3.5 py-2 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  />
                </div>
                <div>
                  <label className="block text-sm text-gray-700 dark:text-gray-300 mb-1">UF/Estado</label>
                  <input
                    type="text"
                    value={phState}
                    onChange={e => setPhState(e.target.value)}
                    required
                    className="w-full px-3.5 py-2 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  />
                </div>
                <div>
                  <label className="block text-sm text-gray-700 dark:text-gray-300 mb-1">País (ISO)</label>
                  <input
                    type="text"
                    value={phCountry}
                    onChange={e => setPhCountry(e.target.value.toUpperCase())}
                    required
                    minLength={2}
                    maxLength={2}
                    className="w-full px-3.5 py-2 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-sm text-gray-700 dark:text-gray-300 mb-1">Área (m²)</label>
                  <input
                    type="number"
                    step="0.01"
                    value={phAreaM2}
                    onChange={e => setPhAreaM2(e.target.value)}
                    className="w-full px-3.5 py-2 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  />
                </div>
                <div>
                  <label className="block text-sm text-gray-700 dark:text-gray-300 mb-1">Matrícula</label>
                  <input
                    type="text"
                    value={phRegistration}
                    onChange={e => setPhRegistration(e.target.value)}
                    className="w-full px-3.5 py-2 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  />
                </div>
              </div>
            </div>
          )}

          {isVehicle && (
            <div className="border-t border-gray-200 dark:border-gray-700 pt-4 space-y-3">
              <div className="grid grid-cols-3 gap-3">
                <div>
                  <label className="block text-sm text-gray-700 dark:text-gray-300 mb-1">Marca</label>
                  <input
                    type="text"
                    value={phMake}
                    onChange={e => setPhMake(e.target.value)}
                    required
                    className="w-full px-3.5 py-2 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  />
                </div>
                <div>
                  <label className="block text-sm text-gray-700 dark:text-gray-300 mb-1">Modelo</label>
                  <input
                    type="text"
                    value={phModel}
                    onChange={e => setPhModel(e.target.value)}
                    required
                    className="w-full px-3.5 py-2 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  />
                </div>
                <div>
                  <label className="block text-sm text-gray-700 dark:text-gray-300 mb-1">Ano</label>
                  <input
                    type="number"
                    value={phYear}
                    onChange={e => setPhYear(e.target.value)}
                    required
                    className="w-full px-3.5 py-2 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-sm text-gray-700 dark:text-gray-300 mb-1">Placa</label>
                  <input
                    type="text"
                    value={phLicensePlate}
                    onChange={e => setPhLicensePlate(e.target.value.toUpperCase())}
                    className="w-full px-3.5 py-2 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  />
                </div>
                <div>
                  <label className="block text-sm text-gray-700 dark:text-gray-300 mb-1">Chassi</label>
                  <input
                    type="text"
                    value={phChassis}
                    onChange={e => setPhChassis(e.target.value)}
                    className="w-full px-3.5 py-2 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  />
                </div>
              </div>
            </div>
          )}

          <div>
            <label className="block text-sm text-gray-700 dark:text-gray-300 mb-1">Notas (opcional)</label>
            <textarea
              value={notes}
              onChange={e => setNotes(e.target.value)}
              rows={2}
              className="w-full px-3.5 py-2 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
          </div>

          {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}

          <div className="flex justify-end gap-3 pt-2">
            <button type="button" onClick={onClose} className="px-4 py-2 rounded-lg text-sm text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors">
              Cancelar
            </button>
            <button type="submit" disabled={saving} className="px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-700 disabled:opacity-60 text-white text-sm font-medium transition-colors">
              {saving ? 'Salvando…' : 'Salvar'}
            </button>
          </div>
        </form>

        {initial && (
          <div className="mt-6 pt-5 border-t border-gray-200 dark:border-gray-700">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-semibold text-gray-900 dark:text-white">Posição</h3>
              <Link
                to={`/lancamentos`}
                className="text-xs px-3 py-1 rounded-lg border border-indigo-200 dark:border-indigo-800 text-indigo-600 dark:text-indigo-300 hover:bg-indigo-50 dark:hover:bg-indigo-900/20 transition-colors"
              >
                Ver lançamentos
              </Link>
            </div>
            {posLoading ? (
              <p className="text-xs text-gray-400">Carregando posição…</p>
            ) : position ? (
              <div className="grid grid-cols-2 gap-3 text-sm">
                <div>
                  <p className="text-xs text-gray-500 dark:text-gray-400">Quantidade</p>
                  <p className="font-mono text-gray-900 dark:text-white">{position.quantity_held.toLocaleString('pt-BR', { maximumFractionDigits: 8 })}</p>
                </div>
                <div>
                  <p className="text-xs text-gray-500 dark:text-gray-400">Custo médio ({position.currency})</p>
                  <p className="font-mono text-gray-900 dark:text-white">{position.average_cost.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 8 })}</p>
                </div>
                <div>
                  <p className="text-xs text-gray-500 dark:text-gray-400">Investido (BRL)</p>
                  <p className="font-mono text-gray-900 dark:text-white">{position.total_invested_brl.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })}</p>
                </div>
                <div>
                  <p className="text-xs text-gray-500 dark:text-gray-400">Recebido (BRL)</p>
                  <p className="font-mono text-gray-900 dark:text-white">{position.total_received_brl.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })}</p>
                </div>
              </div>
            ) : null}

            <div className="mt-4">
              <h4 className="text-xs uppercase tracking-wide text-gray-400 dark:text-gray-500 mb-2">Lançamentos recentes</h4>
              {recentLans.length === 0 ? (
                <p className="text-xs text-gray-400 italic">Nenhum lançamento.</p>
              ) : (
                <ul className="divide-y divide-gray-100 dark:divide-gray-800">
                  {recentLans.map(l => (
                    <li key={l.id} className="py-2 flex items-center justify-between text-xs">
                      <span className="text-gray-600 dark:text-gray-400 w-24">{l.event_date}</span>
                      <span className="text-gray-900 dark:text-white flex-1">{l.type_label}</span>
                      <span className="font-mono text-gray-600 dark:text-gray-400">
                        {l.net_amount.toLocaleString('pt-BR', { style: 'currency', currency: l.currency })}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

export { CLASS_LABELS }
