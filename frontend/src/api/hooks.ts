import { useQuery } from '@tanstack/react-query'
import { api } from './client'

export type Me = { id: number; email: string; display_name: string | null; role: string }
export type Entitlements = {
  tier: string
  features: Record<string, boolean>
  grace: { expires_at: string; grace_until: string; in_grace: boolean } | null
}

export function useMe() {
  return useQuery({ queryKey: ['me'], queryFn: () => api<Me>('/auth/me') })
}

export function useEntitlements() {
  const q = useQuery({
    queryKey: ['entitlements'],
    queryFn: () => api<Entitlements>('/entitlements'),
    refetchInterval: 5 * 60_000,
  })
  return {
    ...q,
    tier: q.data?.tier ?? 'builtin',
    grace: q.data?.grace ?? null,
    has: (key: string) => q.data?.features[key] ?? false,
  }
}
