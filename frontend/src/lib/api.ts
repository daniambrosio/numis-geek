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

  createFinancialInstitution: (data: { long_name: string; short_name: string; logo_slug?: string }) =>
    request<FinancialInstitutionOut>('/financial-institutions', { method: 'POST', body: JSON.stringify(data) }),

  updateFinancialInstitution: (id: string, data: { long_name: string; short_name: string; logo_slug?: string }) =>
    request<FinancialInstitutionOut>(`/financial-institutions/${id}`, { method: 'PUT', body: JSON.stringify(data) }),

  deactivateFinancialInstitution: (id: string) =>
    request<FinancialInstitutionOut>(`/financial-institutions/${id}/deactivate`, { method: 'PUT' }),
}
