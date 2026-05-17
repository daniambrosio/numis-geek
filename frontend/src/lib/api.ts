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
  | 'STOCK_BR'
  | 'STOCK_US'
  | 'FII'
  | 'ETF'
  | 'REIT'
  | 'BOND'
  | 'FIXED_INCOME'
  | 'FUND'
  | 'CRYPTO'
  | 'REAL_ESTATE'
  | 'VEHICLE'
  | 'PRIVATE_PENSION'
  | 'FGTS'
  | 'CASH'

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

export interface AssetOut {
  id: string
  workspace_id: string
  workspace_name: string | null
  financial_institution_id: string
  financial_institution_name: string
  asset_class: AssetClass
  name: string
  ticker: string | null
  cnpj: string | null
  currency: 'BRL' | 'USD'
  notes: string | null
  external_id: string | null
  external_source: ExternalSource | null
  is_active: boolean
  created_at: string
  updated_at: string
  details: FixedIncomeDetails | PhysicalDetails | null
}

export interface AssetRequest {
  asset_class: AssetClass
  financial_institution_id: string
  name: string
  currency: 'BRL' | 'USD'
  ticker?: string | null
  cnpj?: string | null
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

export const ASSET_MOVEMENT_TYPE_LABELS: Record<AssetMovementType, string> = {
  BUY: 'Compra',
  SELL: 'Venda',
  COME_COTAS: 'Come-cotas',
  BONUS: 'Bonificação',
  SUBSCRIPTION: 'Subscrição',
  FULL_REDEMPTION: 'Resgate Total',
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
}
