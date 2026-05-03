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
  const res = await fetch(`${BASE}${path}`, {
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    ...options,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Unknown error' }))
    throw new Error(err.detail ?? 'Request failed')
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

export interface AssetOut {
  id: string
  workspace_id: string
  workspace_name: string | null
  financial_institution_id: string
  financial_institution_name: string
  asset_class: AssetClass
  subtype: string | null
  name: string
  ticker: string | null
  cnpj: string | null
  currency: 'BRL' | 'USD'
  notes: string | null
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
  subtype?: string | null
  ticker?: string | null
  cnpj?: string | null
  notes?: string | null
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
}
