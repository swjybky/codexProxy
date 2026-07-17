const API_BASE = import.meta.env.VITE_API_BASE_URL ?? (import.meta.env.DEV ? 'http://127.0.0.1:1455' : '')

const hashParams = new URLSearchParams(window.location.hash.replace(/^#/, ''))
const hashAdminToken = hashParams.get('admin_token') ?? ''
if (hashAdminToken) {
  window.sessionStorage.setItem('codex_proxy_admin_token', hashAdminToken)
  window.history.replaceState(null, '', window.location.pathname + window.location.search)
}
const ADMIN_TOKEN = hashAdminToken || window.sessionStorage.getItem('codex_proxy_admin_token') || ''

export interface CredentialsSummary {
  configured: boolean
  account_id?: string
  email?: string
  expired?: string
  last_refresh?: string
  refreshable?: boolean
}

export interface ProxySettings {
  listen_port: number
  upstream_base_url: string
  proxy_url: string
  system_prompt: string
  system_prompt_override: boolean
  default_model: string
}

export interface StatusData {
  service: {
    uptime_seconds: number
    request_count: number
    success_count: number
    last_request_at: string
    last_status: number
  }
  credentials: CredentialsSummary
  endpoint: string
  lan_endpoint: string | null
  local_api_key: string
  settings: ProxySettings
  models: string[]
}

export type UsageRange = '24h' | '7d' | '30d' | 'all'

export interface ManagedKey {
  id: string
  name: string
  key: string
  token_limit: number
  used_tokens: number
  remaining_tokens: number
  created_at: string
}

export interface UsageData {
  range: UsageRange
  bucket: 'hour' | 'day'
  key_id: string
  totals: {
    total_tokens: number
    input_tokens: number
    output_tokens: number
    cached_tokens: number
  }
  points: Array<{
    timestamp: string
    input_tokens: number
    output_tokens: number
    cached_tokens: number
  }>
}

interface ApiErrorPayload {
  error?: { message?: string }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    'X-Admin-Token': ADMIN_TOKEN,
    ...(init?.headers as Record<string, string> | undefined),
  }
  if (init?.body) headers['Content-Type'] = 'application/json'
  const response = await fetch(API_BASE + path, {
    ...init,
    headers,
  })
  const payload = (await response.json().catch(() => ({}))) as T & ApiErrorPayload
  if (!response.ok) {
    throw new Error(payload.error?.message || `请求失败（HTTP ${response.status}）`)
  }
  return payload
}

export const api = {
  status: () => request<StatusData>('/api/status'),
  usage: (range: UsageRange, keyId = 'all') =>
    request<UsageData>(`/api/usage?range=${range}&key_id=${encodeURIComponent(keyId)}`),
  keys: () => request<{ keys: ManagedKey[] }>('/api/keys'),
  createKey: (name: string, tokenLimit: number) =>
    request<{ key: ManagedKey }>('/api/keys', {
      method: 'POST',
      body: JSON.stringify({ name, token_limit: tokenLimit }),
    }),
  updateKeyLimit: (keyId: string, tokenLimit: number) =>
    request<{ key: ManagedKey }>(`/api/keys/${encodeURIComponent(keyId)}`, {
      method: 'PUT',
      body: JSON.stringify({ token_limit: tokenLimit }),
    }),
  resetKeyUsage: (keyId: string) =>
    request<{ key: ManagedKey }>(`/api/keys/${encodeURIComponent(keyId)}/reset`, { method: 'POST' }),
  deleteKey: (keyId: string) =>
    request<{ deleted: boolean }>(`/api/keys/${encodeURIComponent(keyId)}`, { method: 'DELETE' }),
  saveSettings: (settings: Partial<ProxySettings>) =>
    request<{ settings: ProxySettings }>('/api/settings', {
      method: 'PUT',
      body: JSON.stringify(settings),
    }),
  importDefaultCredentials: () =>
    request<{ credentials: CredentialsSummary }>('/api/credentials/import-default', { method: 'POST' }),
  importCredentials: (raw: string) =>
    request<{ credentials: CredentialsSummary }>('/api/credentials/import', {
      method: 'POST',
      body: JSON.stringify({ raw }),
    }),
  refreshCredentials: () =>
    request<{ credentials: CredentialsSummary }>('/api/credentials/refresh', { method: 'POST' }),
  regenerateKey: () =>
    request<{ local_api_key: string }>('/api/key/regenerate', { method: 'POST' }),
  testConnection: (model: string) =>
    request<{ ok: boolean; response_id: string; model: string }>('/api/connection-test', {
      method: 'POST',
      body: JSON.stringify({ model }),
    }),
}
