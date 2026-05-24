const BASE = '/api'

export function getToken(): string | null {
  return localStorage.getItem('token') ?? sessionStorage.getItem('token')
}

export function setToken(token: string, remember: boolean) {
  if (remember) {
    localStorage.setItem('token', token)
    sessionStorage.removeItem('token')
  } else {
    sessionStorage.setItem('token', token)
    localStorage.removeItem('token')
  }
}

export function clearToken() {
  localStorage.removeItem('token')
  sessionStorage.removeItem('token')
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const token = getToken()
  let res: Response
  try {
    res = await fetch(`${BASE}${path}`, {
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      ...options,
    })
  } catch {
    throw new Error('Não foi possível conectar ao servidor. Verifique se o backend está rodando.')
  }
  if (!res.ok) {
    let detail: unknown = null
    let bodyText = ''
    try {
      bodyText = await res.text()
      detail = bodyText ? JSON.parse(bodyText)?.detail : null
    } catch {
      // body wasn't JSON; bodyText still set above
    }
    let message: string
    if (typeof detail === 'string') {
      message = detail
    } else if (Array.isArray(detail) && detail.length > 0) {
      // FastAPI 422: array of {loc, msg, type, ...}
      message = detail
        .map((e) => {
          if (e && typeof e === 'object' && 'msg' in e) {
            const loc = Array.isArray((e as { loc?: unknown[] }).loc)
              ? (e as { loc: unknown[] }).loc.slice(1).join('.')
              : ''
            const msg = (e as { msg: string }).msg
            return loc ? `${loc}: ${msg}` : msg
          }
          return String(e)
        })
        .join('; ')
    } else {
      const status = `HTTP ${res.status}${res.statusText ? ' ' + res.statusText : ''}`
      const snippet = bodyText && bodyText.length < 200 ? ` — ${bodyText}` : ''
      message = `${status}${snippet}`
    }
    throw new Error(message)
  }
  if (res.status === 204) return undefined as T
  return res.json()
}

export interface UserOut {
  id: string
  email: string
  name: string | null
  role: string
  is_active: boolean
  created_at: string
  workspace_id: string | null
  workspace_name: string | null
}

export interface FinancialInstitutionOut {
  id: string
  long_name: string
  short_name: string
  logo_slug: string | null
  country: string  // ISO-2
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface AccountOut {
  id: string
  workspace_id: string
  financial_institution_id: string
  financial_institution_name: string
  name: string
  account_type: 'checking' | 'investment'
  currency: 'BRL' | 'USD'
  opening_balance: number | null
  account_info: string | null
  is_active: boolean
  created_at: string
}

export type AssetClass =
  | 'STOCK'
  | 'REIT'
  | 'ETF'
  | 'FIXED_INCOME'
  | 'FUND'
  | 'CRYPTO'
  | 'REAL_ESTATE'
  | 'VEHICLE'
  | 'CASH'
  | 'FGTS'
  | 'PRIVATE_PENSION'
  | 'OPTION'

export type OptionType = 'CALL' | 'PUT'

export type FixedIncomeIndexer = 'CDI' | 'IPCA' | 'SELIC' | 'PREFIXED' | 'USD'

export interface FixedIncomeDetails {
  issuer: string
  issue_date: string | null
  maturity_date: string
  indexer: FixedIncomeIndexer
  rate: number
  face_value: number | null
}

export interface PhysicalDetails {
  address: string | null
  city: string | null
  state: string | null
  country: string | null
  area_m2: number | null
  registration_number: string | null
  make: string | null
  model: string | null
  year: number | null
  license_plate: string | null
  chassis: string | null
}

export type ExternalSource = 'NOTION' | 'B3' | 'BROKER_NOTE' | 'MANUAL_CSV'

export type PriceSource =
  | 'BRAPI'
  | 'FINNHUB'
  | 'COINBASE'
  | 'TESOURO'
  | 'MANUAL'

export type PriceTier = 'FRESH' | 'STALE' | 'OLD' | 'UNKNOWN'

export interface AssetOut {
  id: string
  workspace_id: string
  workspace_name: string | null
  account_id: string
  account_name: string
  financial_institution_id: string
  financial_institution_name: string
  asset_class: AssetClass
  country: string
  name: string
  ticker: string | null
  cnpj: string | null
  currency: 'BRL' | 'USD'
  current_price: number | null
  price_updated_at: string | null
  price_source: PriceSource | null
  price_tier: PriceTier
  notes: string | null
  external_id: string | null
  external_source: ExternalSource | null
  is_active: boolean
  /** Option-specific fields (Spec 17). Null for non-OPTION assets. */
  underlying_id?: string | null
  option_type?: OptionType | null
  strike_price?: number | null
  expiration_date?: string | null
  contract_size?: number | null
  created_at: string
  updated_at: string
  details: FixedIncomeDetails | PhysicalDetails | null
}

export interface AssetRequest {
  asset_class: AssetClass
  account_id: string
  country: string
  name: string
  currency: 'BRL' | 'USD'
  ticker?: string | null
  cnpj?: string | null
  current_price?: number | null
  notes?: string | null
  external_id?: string | null
  external_source?: ExternalSource | null
  workspace_id?: string | null
  details?: Record<string, unknown> | null
}

export interface WorkspaceOut {
  id: string
  name: string
}

export interface AuditLogOut {
  id: string
  user_email: string
  action: string
  resource_type: string | null
  resource_id: string | null
  details: string | null
  created_at: string
}

export interface AuditPage {
  items: AuditLogOut[]
  total: number
  page: number
  pages: number
}

export type AssetMovementType =
  | 'BUY'
  | 'SELL'
  | 'COME_COTAS'
  | 'BONUS'
  | 'SUBSCRIPTION'
  | 'FULL_REDEMPTION'
  | 'SELL_OPEN'
  | 'BUY_TO_OPEN'
  | 'BUY_TO_CLOSE'
  | 'SELL_TO_CLOSE'
  | 'EXERCISED'
  | 'EXPIRED'

export const ASSET_MOVEMENT_TYPE_LABELS: Record<AssetMovementType, string> = {
  BUY: 'Compra',
  SELL: 'Venda',
  COME_COTAS: 'Come-cotas',
  BONUS: 'Bonificação',
  SUBSCRIPTION: 'Subscrição',
  FULL_REDEMPTION: 'Resgate Total',
  SELL_OPEN: 'Venda pra abrir',
  BUY_TO_OPEN: 'Compra pra abrir',
  BUY_TO_CLOSE: 'Compra pra fechar',
  SELL_TO_CLOSE: 'Venda pra fechar',
  EXERCISED: 'Exercida',
  EXPIRED: 'Vencida (pó)',
}

export interface AssetMovementOut {
  id: string
  workspace_id: string
  asset_id: string
  asset_name: string
  asset_ticker: string | null
  type: AssetMovementType
  type_label: string
  event_date: string
  settlement_date: string | null
  quantity: number | null
  unit_price: number | null
  gross_amount: number | null
  fee: number | null
  tax: number | null
  net_amount: number
  currency: 'BRL' | 'USD'
  fx_rate: number
  notes: string | null
  external_id: string | null
  external_source: ExternalSource | null
  nota_negociacao_number: string | null
  notion_sync_status: NotionSyncStatus
  notion_sync_error: string | null
  notion_last_synced_at: string | null
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface AssetMovementListPage {
  items: AssetMovementOut[]
  total: number
  page: number
  page_size: number
}

export interface AssetMovementRequest {
  asset_id: string
  type: AssetMovementType
  event_date: string
  settlement_date?: string | null
  quantity?: number | null
  unit_price?: number | null
  gross_amount?: number | null
  fee?: number | null
  tax?: number | null
  net_amount?: number | null
  currency?: 'BRL' | 'USD' | null
  fx_rate?: number | null
  notes?: string | null
  external_id?: string | null
  external_source?: ExternalSource | null
  nota_negociacao_number?: string | null
  workspace_id?: string | null
}

export type DistributionType = 'DIVIDEND' | 'INTEREST' | 'JCP' | 'SECURITIES_LENDING'

export const DISTRIBUTION_TYPE_LABELS: Record<DistributionType, string> = {
  DIVIDEND: 'Dividendo',
  INTEREST: 'Juros / Cupom',
  JCP: 'JCP',
  SECURITIES_LENDING: 'Aluguel',
}

export interface DistributionOut {
  id: string
  workspace_id: string
  financial_institution_id: string
  financial_institution_name: string
  asset_id: string | null
  asset_name: string | null
  asset_ticker: string | null
  type: DistributionType
  type_label: string
  event_date: string
  gross_amount: number
  tax: number | null
  net_amount: number
  currency: 'BRL' | 'USD'
  fx_rate: number
  notes: string | null
  external_id: string | null
  external_source: ExternalSource | null
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface DistributionListPage {
  items: DistributionOut[]
  total: number
  page: number
  page_size: number
}

export interface DistributionRequest {
  financial_institution_id: string
  asset_id?: string | null
  type: DistributionType
  event_date: string
  gross_amount: number
  tax?: number | null
  net_amount?: number | null
  currency?: 'BRL' | 'USD' | null
  fx_rate?: number | null
  notes?: string | null
  external_id?: string | null
  external_source?: ExternalSource | null
  workspace_id?: string | null
}

export interface PositionOut {
  asset_id: string
  quantity_held: number
  average_cost: number
  average_cost_brl: number
  total_invested_brl: number
  total_received_brl: number
  currency: string
  current_price: number | null
  current_value: number | null
  current_value_brl: number | null
  variation: number | null
  rentabilidade: number | null
}

export interface CustodianGroupOut {
  financial_institution: {
    id: string
    short_name: string
    long_name: string
    logo_slug: string | null
  }
  accounts: AccountOut[]
  assets: {
    id: string
    workspace_id: string
    name: string
    ticker: string | null
    asset_class: AssetClass
    currency: 'BRL' | 'USD'
  }[]
}

// ── Integration Credentials (sysadmin) ──────────────────────────────────────
export type IntegrationProvider = 'BCB' | 'BRAPI' | 'FINNHUB' | 'YFINANCE' | 'NOTION'
export type CredentialTestResult = 'UNTESTED' | 'SUCCESS' | 'FAILED'

export interface IntegrationCredentialOut {
  id: string
  provider: IntegrationProvider
  provider_label: string
  key_name: string
  label: string | null
  secret_preview: string
  is_active: boolean
  last_tested_at: string | null
  last_test_result: CredentialTestResult
  last_test_message: string | null
  created_at: string
  updated_at: string
}

export interface IntegrationCredentialRequest {
  provider: IntegrationProvider
  key_name: string
  label?: string | null
  secret_value: string
}

export interface IntegrationCredentialPatch {
  label?: string | null
  secret_value?: string | null
  is_active?: boolean | null
}

export interface ProviderCatalogEntry {
  provider: IntegrationProvider
  label: string
  requires_credentials: boolean
}

export interface TestResultOut {
  result: CredentialTestResult
  message: string
  tested_at: string
}

// ── PTAX ────────────────────────────────────────────────────────────────────
export interface PTAXRateOut {
  id: string
  date: string
  rate: string
  source: string
  fetched_at: string
}

export interface PTAXListOut {
  items: PTAXRateOut[]
  total: number
  page: number
  page_size: number
}

export interface PTAXStatusOut {
  total_rows: number
  last_date: string | null
  oldest_date: string | null
  last_fetched_at: string | null
}

export type PTAXSyncMode = 'incremental' | 'full'

export interface PTAXSyncResultOut {
  mode: PTAXSyncMode
  fetched_count: number
  inserted_count: number
  updated_count: number
  range_start: string
  range_end: string
  duration_ms: number
}

export const api = {
  login: (email: string, password: string, remember_me = false) =>
    request<{ access_token: string }>('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password, remember_me }),
    }),

  me: () => request<UserOut>('/users/me'),

  updateMe: (name: string) =>
    request<UserOut>('/users/me', { method: 'PUT', body: JSON.stringify({ name }) }),

  changePassword: (current_password: string, new_password: string) =>
    request<void>('/users/me/password', {
      method: 'PUT',
      body: JSON.stringify({ current_password, new_password }),
    }),

  listUsers: () => request<UserOut[]>('/users'),

  inviteUser: (data: { email: string; name?: string; password: string; role: string }) =>
    request<UserOut>('/users/invite', { method: 'POST', body: JSON.stringify(data) }),

  changeRole: (userId: string, role: string) =>
    request<UserOut>(`/users/${userId}/role`, { method: 'PUT', body: JSON.stringify({ role }) }),

  deactivateUser: (userId: string) =>
    request<UserOut>(`/users/${userId}/deactivate`, { method: 'PUT' }),

  updateUserName: (userId: string, name: string) =>
    request<UserOut>(`/users/${userId}/name`, { method: 'PUT', body: JSON.stringify({ name }) }),

  listAudit: (page = 1, action?: string) => {
    const params = new URLSearchParams({ page: String(page), limit: '50' })
    if (action) params.set('action', action)
    return request<AuditPage>(`/audit?${params}`)
  },

  listFinancialInstitutions: () =>
    request<FinancialInstitutionOut[]>('/financial-institutions'),

  createFinancialInstitution: (data: { long_name: string; short_name: string; logo_slug?: string | null }) =>
    request<FinancialInstitutionOut>('/financial-institutions', { method: 'POST', body: JSON.stringify(data) }),

  updateFinancialInstitution: (id: string, data: { long_name: string; short_name: string; logo_slug?: string | null }) =>
    request<FinancialInstitutionOut>(`/financial-institutions/${id}`, { method: 'PUT', body: JSON.stringify(data) }),

  deactivateFinancialInstitution: (id: string) =>
    request<FinancialInstitutionOut>(`/financial-institutions/${id}/deactivate`, { method: 'PUT' }),

  listAccounts: () => request<AccountOut[]>('/accounts'),

  getAccount: async (id: string) => {
    const all = await request<AccountOut[]>('/accounts')
    const a = all.find(ac => ac.id === id)
    if (!a) throw new Error(`Account ${id} not found`)
    return a
  },

  createAccount: (data: {
    name: string
    account_type: string
    financial_institution_id: string
    currency: string
    opening_balance?: number | null
    account_info?: string | null
  }) => request<AccountOut>('/accounts', { method: 'POST', body: JSON.stringify(data) }),

  updateAccount: (id: string, data: {
    name: string
    account_type: string
    financial_institution_id: string
    currency: string
    opening_balance?: number | null
    account_info?: string | null
  }) => request<AccountOut>(`/accounts/${id}`, { method: 'PUT', body: JSON.stringify(data) }),

  deactivateAccount: (id: string) =>
    request<AccountOut>(`/accounts/${id}/deactivate`, { method: 'PUT' }),

  listWorkspaces: () => request<WorkspaceOut[]>('/workspaces'),

  listAssets: (params?: { workspace_id?: string; asset_class?: AssetClass; include_inactive?: boolean; search?: string }) => {
    const qs = new URLSearchParams()
    if (params?.workspace_id) qs.set('workspace_id', params.workspace_id)
    if (params?.asset_class) qs.set('asset_class', params.asset_class)
    if (params?.include_inactive) qs.set('include_inactive', 'true')
    if (params?.search) qs.set('search', params.search)
    const suffix = qs.toString()
    return request<AssetOut[]>(`/assets${suffix ? `?${suffix}` : ''}`)
  },

  getAsset: (id: string) => request<AssetOut>(`/assets/${id}`),

  createAsset: (data: AssetRequest) =>
    request<AssetOut>('/assets', { method: 'POST', body: JSON.stringify(data) }),

  updateAsset: (id: string, data: AssetRequest) =>
    request<AssetOut>(`/assets/${id}`, { method: 'PUT', body: JSON.stringify(data) }),

  deactivateAsset: (id: string) =>
    request<AssetOut>(`/assets/${id}/deactivate`, { method: 'PUT' }),

  getAssetPosition: (id: string) =>
    request<PositionOut>(`/assets/${id}/position`),

  listAssetMovementsForAsset: (id: string, params?: { page?: number; page_size?: number; include_inactive?: boolean }) => {
    const qs = new URLSearchParams()
    if (params?.page) qs.set('page', String(params.page))
    if (params?.page_size) qs.set('page_size', String(params.page_size))
    if (params?.include_inactive) qs.set('include_inactive', 'true')
    const suffix = qs.toString()
    return request<AssetMovementListPage>(`/assets/${id}/asset-movements${suffix ? `?${suffix}` : ''}`)
  },

  listAssetMovements: (params?: {
    asset_id?: string
    type?: AssetMovementType
    from?: string
    to?: string
    include_inactive?: boolean
    page?: number
    page_size?: number
    workspace_id?: string
  }) => {
    const qs = new URLSearchParams()
    if (params?.asset_id) qs.set('asset_id', params.asset_id)
    if (params?.type) qs.set('type', params.type)
    if (params?.from) qs.set('from', params.from)
    if (params?.to) qs.set('to', params.to)
    if (params?.include_inactive) qs.set('include_inactive', 'true')
    if (params?.page) qs.set('page', String(params.page))
    if (params?.page_size) qs.set('page_size', String(params.page_size))
    if (params?.workspace_id) qs.set('workspace_id', params.workspace_id)
    const suffix = qs.toString()
    return request<AssetMovementListPage>(`/asset-movements${suffix ? `?${suffix}` : ''}`)
  },

  getAssetMovement: (id: string) =>
    request<AssetMovementOut>(`/asset-movements/${id}`),

  createAssetMovement: (data: AssetMovementRequest) =>
    request<AssetMovementOut>('/asset-movements', { method: 'POST', body: JSON.stringify(data) }),

  updateAssetMovement: (id: string, data: AssetMovementRequest) =>
    request<AssetMovementOut>(`/asset-movements/${id}`, { method: 'PUT', body: JSON.stringify(data) }),

  deactivateAssetMovement: (id: string) =>
    request<AssetMovementOut>(`/asset-movements/${id}/deactivate`, { method: 'PUT' }),

  listDistributionsForAsset: (asset_id: string, params?: { page?: number; page_size?: number; include_inactive?: boolean }) => {
    const qs = new URLSearchParams({ asset_id })
    if (params?.page) qs.set('page', String(params.page))
    if (params?.page_size) qs.set('page_size', String(params.page_size))
    if (params?.include_inactive) qs.set('include_inactive', 'true')
    return request<DistributionListPage>(`/distributions?${qs}`)
  },

  listDistributions: (params?: {
    asset_id?: string
    financial_institution_id?: string
    type?: DistributionType
    from?: string
    to?: string
    include_inactive?: boolean
    page?: number
    page_size?: number
    workspace_id?: string
  }) => {
    const qs = new URLSearchParams()
    if (params?.asset_id) qs.set('asset_id', params.asset_id)
    if (params?.financial_institution_id) qs.set('financial_institution_id', params.financial_institution_id)
    if (params?.type) qs.set('type', params.type)
    if (params?.from) qs.set('from', params.from)
    if (params?.to) qs.set('to', params.to)
    if (params?.include_inactive) qs.set('include_inactive', 'true')
    if (params?.page) qs.set('page', String(params.page))
    if (params?.page_size) qs.set('page_size', String(params.page_size))
    if (params?.workspace_id) qs.set('workspace_id', params.workspace_id)
    const suffix = qs.toString()
    return request<DistributionListPage>(`/distributions${suffix ? `?${suffix}` : ''}`)
  },

  createDistribution: (data: DistributionRequest) =>
    request<DistributionOut>('/distributions', { method: 'POST', body: JSON.stringify(data) }),

  updateDistribution: (id: string, data: DistributionRequest) =>
    request<DistributionOut>(`/distributions/${id}`, { method: 'PUT', body: JSON.stringify(data) }),

  deactivateDistribution: (id: string) =>
    request<DistributionOut>(`/distributions/${id}/deactivate`, { method: 'PUT' }),

  listAccountsByCustodian: (workspace_id?: string) => {
    const qs = workspace_id ? `?workspace_id=${workspace_id}` : ''
    return request<CustodianGroupOut[]>(`/accounts/by-custodian${qs}`)
  },

  // ── Integrations ──────────────────────────────────────────────────────────
  listIntegrationProviders: () =>
    request<ProviderCatalogEntry[]>('/sysadmin/integrations/providers'),

  listIntegrations: () =>
    request<IntegrationCredentialOut[]>('/sysadmin/integrations'),

  createIntegration: (data: IntegrationCredentialRequest) =>
    request<IntegrationCredentialOut>('/sysadmin/integrations', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  updateIntegration: (id: string, data: IntegrationCredentialPatch) =>
    request<IntegrationCredentialOut>(`/sysadmin/integrations/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    }),

  deleteIntegration: (id: string) =>
    request<void>(`/sysadmin/integrations/${id}`, { method: 'DELETE' }),

  testIntegration: (id: string) =>
    request<TestResultOut>(`/sysadmin/integrations/${id}/test`, { method: 'POST' }),

  // ── PTAX ──────────────────────────────────────────────────────────────────
  ptaxStatus: () => request<PTAXStatusOut>('/sysadmin/ptax/status'),

  listPtax: (page = 1, page_size = 50) =>
    request<PTAXListOut>(`/sysadmin/ptax?page=${page}&page_size=${page_size}`),

  syncPtax: (mode: PTAXSyncMode) =>
    request<PTAXSyncResultOut>('/sysadmin/ptax/sync', {
      method: 'POST',
      body: JSON.stringify({ mode }),
    }),

  // ── Price refresh (spec 12 + 23) ─────────────────────────────────────────
  refreshAssetPrice: (id: string) =>
    request<PriceRefreshOut>(`/assets/${id}/refresh-price`, { method: 'POST' }),

  refreshPrices: (body?: { source?: PriceSource; asset_ids?: string[] }) =>
    request<RefreshSummaryOut>('/prices/refresh', {
      method: 'POST',
      body: JSON.stringify(body ?? {}),
    }),

  /** @deprecated use refreshPrices(). Sunset 2026-12-31. */
  refreshPricesBulk: (only_country?: 'BR' | 'US') => {
    const qs = only_country ? `?only_country=${only_country}` : ''
    return request<BulkRefreshSummaryOut>(`/assets/refresh-prices/bulk${qs}`, { method: 'POST' })
  },

  // ── Snapshots (spec 14) ──────────────────────────────────────────────────
  listSnapshots: () => request<SnapshotOut[]>('/snapshots'),
  createSnapshot: (period_end_date: string) =>
    request<SnapshotOut>('/snapshots', {
      method: 'POST',
      body: JSON.stringify({ period_end_date }),
    }),

  // ── Notion sync (spec 16) ────────────────────────────────────────────────
  notionPending: () => request<PendingCountsOut>('/notion-sync/pending'),
  notionPushAsset: (id: string, force = false) =>
    request<SyncOut>(`/notion-sync/asset/${id}${force ? '?force=true' : ''}`, { method: 'POST' }),
  notionPushMovement: (id: string, force = false) =>
    request<SyncOut>(`/notion-sync/asset-movement/${id}${force ? '?force=true' : ''}`, { method: 'POST' }),
  notionPushSnapshot: (id: string, force = false) =>
    request<SyncOut>(`/notion-sync/snapshot/${id}${force ? '?force=true' : ''}`, { method: 'POST' }),
  notionPushCorporateAction: (id: string, force = false) =>
    request<SyncOut>(`/notion-sync/corporate-action/${id}${force ? '?force=true' : ''}`, { method: 'POST' }),
  notionBulk: (entity: NotionEntity) =>
    request<BulkSyncOut>(`/notion-sync/${entity}/bulk`, { method: 'POST' }),
  notionResolve: (entity: NotionEntity, id: string, action: 'force_push' | 'abort') =>
    request<SyncOut>(`/notion-sync/${entity}/${id}/resolve?action=${action}`, { method: 'POST' }),

  // ── Options (spec 17) ────────────────────────────────────────────────────
  parseOption: (ticker: string, underlying_price?: number) => {
    const qs = new URLSearchParams({ ticker })
    if (underlying_price != null) qs.set('underlying_price', String(underlying_price))
    return request<ParsedOptionTicker>(`/options/parse?${qs}`)
  },
  createOption: (body: OptionCreateRequest) =>
    request<OptionOut>('/options', { method: 'POST', body: JSON.stringify(body) }),
  getOption: (id: string) => request<OptionOut>(`/options/${id}`),
  listOpenOptionsForUnderlying: (underlying_id: string) =>
    request<OpenOptionOut[]>(`/options/by-underlying/${underlying_id}`),
  exerciseOption: (id: string, exercise_date: string) =>
    request<OptionOut>(`/options/${id}/exercise`, {
      method: 'POST', body: JSON.stringify({ exercise_date }),
    }),
  expireOption: (id: string, expiration_date?: string) =>
    request<OptionOut>(`/options/${id}/expire`, {
      method: 'POST', body: JSON.stringify({ expiration_date: expiration_date ?? null }),
    }),
  closeOption: (id: string, body: {
    close_date: string; quantity: number; price_per_share: number;
    movement_type?: 'BUY_TO_CLOSE' | 'SELL_TO_CLOSE'; fee?: number; notes?: string;
  }) =>
    request<OptionOut>(`/options/${id}/close`, {
      method: 'POST', body: JSON.stringify(body),
    }),

  getPortfolio: (workspace_id?: string) => {
    const qs = workspace_id ? `?workspace_id=${encodeURIComponent(workspace_id)}` : ''
    return request<PortfolioOut>(`/portfolio${qs}`)
  },
}

// ── Portfolio (Spec 20) ──────────────────────────────────────────────────────

export interface PortfolioClassBreakdown {
  asset_class: string
  value_brl: number
  pct: number
}

export interface PortfolioCountryBreakdown {
  country: string
  value_brl: number
  pct: number
}

export interface PortfolioCustodianBreakdown {
  fi_id: string
  fi_short: string
  fi_logo_slug: string | null
  value_brl: number
  pct: number
  asset_count: number
}

export interface PortfolioHolding {
  asset_id: string
  ticker: string | null
  name: string
  asset_class: string
  country: string
  fi_short: string
  fi_logo_slug: string | null
  value_brl: number
  pct: number
}

export interface PortfolioHistoryPoint {
  period_end: string
  total_brl: number
  by_class: Record<string, number>
}

export interface PortfolioOut {
  as_of: string | null
  source: 'snapshot' | 'live' | 'empty'
  ptax_rate: number | null
  total_value_brl: number
  total_value_usd: number
  total_invested_brl: number
  total_received_brl: number
  received_by_type: Record<string, number>  // DIVIDEND | INTEREST | JCP | SECURITIES_LENDING
  by_class: PortfolioClassBreakdown[]
  by_country: PortfolioCountryBreakdown[]
  by_custodian: PortfolioCustodianBreakdown[]
  top_holdings: PortfolioHolding[]
  history: PortfolioHistoryPoint[]
}

export interface SnapshotOut {
  id: string
  workspace_id: string
  period_end_date: string
  fx_rate_usd_brl: string | null
  total_value_brl: string
  total_value_usd: string
  total_invested_brl: string
  total_received_brl: string
  source: string
  items_count: number
}

export interface PriceRefreshOut {
  asset_id: string
  ticker: string | null
  country: string | null
  status: 'ok' | 'skipped' | 'failed'
  provider: string | null
  price_source: PriceSource | null
  old_price: number | null
  new_price: number | null
  error: string | null
}

export interface BulkRefreshSummaryOut {
  total: number
  ok: number
  skipped: number
  failed: number
  results: PriceRefreshOut[]
}

export interface RefreshError {
  asset_id: string
  ticker: string | null
  reason: string | null
}

export interface RefreshSummaryOut {
  ok: number
  failed: number
  skipped: number
  errors: RefreshError[]
  ran_at: string
}

// ── Notion sync (spec 16) ────────────────────────────────────────────────────

export type NotionSyncStatus = 'PENDING' | 'SYNCED' | 'CONFLICT' | 'ERROR'
export type NotionEntity = 'asset' | 'asset-movement' | 'snapshot' | 'corporate-action'

export interface SyncOut {
  status: NotionSyncStatus
  entity_id: string
  notion_page_id: string | null
  notion_url: string | null
  error: string | null
  conflict_remote_edited_at?: string | null
}

export interface BulkSyncOut {
  entity: string
  total: number
  synced: number
  conflicts: number
  errors: number
  results: SyncOut[]
}

export interface PendingCountsOut {
  assets: number
  asset_movements: number
  snapshots: number
  corporate_actions: number
}

// ── Options (spec 17) ────────────────────────────────────────────────────────

export interface OptionOut {
  id: string
  ticker: string
  name: string
  underlying_id: string
  underlying_ticker: string | null
  option_type: OptionType
  strike_price: number
  expiration_date: string
  contract_size: number
  currency: 'BRL' | 'USD'
  is_active: boolean
  account_id: string
  workspace_id: string
}

export interface OpenOptionOut {
  option_id: string
  ticker: string
  name: string
  option_type: OptionType
  strike: number
  expiration_date: string
  days_to_expiration: number
  contract_size: number
  qty: number
  is_short: boolean
  premium_received: number
  premium_per_share: number
  current_price: number | null
  mark_to_market: number | null
  close_now_pnl: number | null
  effective_price: number | null
  verdict: 'likely_exercise' | 'likely_worthless' | 'unknown'
}

export interface ParsedOptionTicker {
  prefix: string
  month: number
  option_type: OptionType
  strike_digits: string
  strike_suggested: number
  adjustment_suffix: string | null
}

export interface OptionCreateRequest {
  ticker: string
  name?: string
  underlying_id: string
  account_id: string
  option_type: OptionType
  strike_price: number
  expiration_date: string
  contract_size?: number
  movement_type?: 'SELL_OPEN' | 'BUY_TO_OPEN'
  movement_date: string
  quantity: number
  price_per_share: number
  fee?: number
  tax?: number
  notes?: string
}
