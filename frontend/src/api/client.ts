export class ApiError extends Error {
  status: number
  body: unknown
  constructor(status: number, body: unknown) {
    super(`API ${status}`)
    this.status = status
    this.body = body
  }
}

function cookie(name: string): string {
  return document.cookie.split('; ').find(c => c.startsWith(name + '='))?.split('=')[1] ?? ''
}

const MUTATING = new Set(['POST', 'PUT', 'PATCH', 'DELETE'])

export async function api<T = unknown>(path: string, opts: RequestInit = {}): Promise<T> {
  const method = (opts.method ?? 'GET').toUpperCase()
  const headers: Record<string, string> = { ...(opts.headers as Record<string, string>) }
  if (opts.body != null) headers['Content-Type'] = 'application/json'
  if (MUTATING.has(method)) headers['X-CSRF-Token'] = cookie('pp_csrf')
  const r = await fetch('/api/v1' + path, { credentials: 'include', ...opts, method, headers })
  const body = r.status === 204 ? null : await r.json().catch(() => null)
  if (!r.ok) throw new ApiError(r.status, body)
  return body as T
}
