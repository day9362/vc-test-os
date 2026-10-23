const BASE = '/api/v1'
const TOKEN = 'vc-token'
const USER = 'vc-user'

export interface Me {
  user_id: string
  name: string
  role: 'process' | 'test' | 'quality' | 'admin'
  tenant_id: string
  tenant_name: string
}

export interface TenantOption {
  tenant_id: string
  name: string
}

async function errorMessage(res: Response): Promise<string> {
  try {
    const body = await res.json()
    return body?.error?.message || `请求失败 ${res.status}`
  } catch {
    return `请求失败 ${res.status}`
  }
}

export function currentToken(): string | null {
  return sessionStorage.getItem(TOKEN)
}

export function currentUser(): Me | null {
  const raw = sessionStorage.getItem(USER)
  if (!raw) return null
  try {
    return JSON.parse(raw) as Me
  } catch {
    return null
  }
}

export function clearSession() {
  sessionStorage.removeItem(TOKEN)
  sessionStorage.removeItem(USER)
}

function remember(token: string, me: Me) {
  sessionStorage.setItem(TOKEN, token)
  sessionStorage.setItem(USER, JSON.stringify(me))
}

function goLogin() {
  if (!location.hash.startsWith('#/login')) location.hash = '#/login'
}

export async function listTenants(): Promise<TenantOption[]> {
  const res = await fetch(`${BASE}/auth/tenants`)
  if (!res.ok) throw new Error(await errorMessage(res))
  return res.json()
}

export async function login(tenant: string, username: string, password: string): Promise<Me> {
  const res = await fetch(`${BASE}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ tenant, username, password }),
  })
  if (!res.ok) throw new Error(await errorMessage(res))
  const body = await res.json()
  const meRes = await fetch(`${BASE}/me`, { headers: { Authorization: `Bearer ${body.token}` } })
  if (!meRes.ok) throw new Error(await errorMessage(meRes))
  const me = (await meRes.json()) as Me
  remember(body.token, me)
  return me
}

export async function logout(): Promise<void> {
  const token = currentToken()
  clearSession()
  if (!token) return
  await fetch(`${BASE}/auth/logout`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
  }).catch(() => undefined)
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = currentToken()
  if (!token) {
    goLogin()
    throw new Error('未登录')
  }
  const headers = new Headers(init.headers)
  headers.set('Authorization', `Bearer ${token}`)
  if (init.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
  const res = await fetch(`${BASE}${path}`, { ...init, headers })
  if (res.status === 401) {
    clearSession()
    goLogin()
    throw new Error(await errorMessage(res))
  }
  if (!res.ok) throw new Error(await errorMessage(res))
  if (res.status === 204) return undefined as T
  return res.json() as Promise<T>
}

export async function apiBlob(path: string): Promise<Blob> {
  const token = currentToken()
  if (!token) {
    goLogin()
    throw new Error('未登录')
  }
  const res = await fetch(`${BASE}${path}`, { headers: { Authorization: `Bearer ${token}` } })
  if (res.status === 401) {
    clearSession()
    goLogin()
  }
  if (!res.ok) throw new Error(await errorMessage(res))
  return res.blob()
}

export async function wsUrl(): Promise<string> {
  const token = currentToken()
  if (!token) {
    goLogin()
    throw new Error('未登录')
  }
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${location.host}/api/v1/ws?token=${encodeURIComponent(token)}`
}
