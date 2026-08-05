import { useQuery } from '@tanstack/react-query'
import { api } from './client'

export type ApiKeyRow = {
  id: number; name: string; prefix: string; scopes: string[]
  expires_at: string | null; last_used_at: string | null
  revoked_at: string | null; created_at: string
}

// `key` is present ONLY on the POST /api-keys response body (apikeys.py) --
// GET/list never returns it again, and nothing here persists it. Component
// state holds it for one render, then it is gone for good.
export type ApiKeyCreated = ApiKeyRow & { key: string }

export function useApiKeys(enabled = true) {
  return useQuery({ queryKey: ['api-keys'], queryFn: () => api<ApiKeyRow[]>('/api-keys'), enabled })
}
