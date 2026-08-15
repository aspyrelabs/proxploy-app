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

/**
 * The shared funnel from a caught ApiError to toast/inline text. FastAPI
 * wraps whatever a route raises as `HTTPException(status, X)` into a
 * response body of `{"detail": X}`, and X is either a plain string or, at
 * roughly 20 call sites that raise 502 when a call to Proxmox itself fails,
 * an object of `{"error": <kind>, "detail": <text>}`. Both shapes are read
 * here so every caller does not have to unwrap the nested one by hand.
 *
 * `fallback` is caller-supplied on purpose: it is user-facing copy specific
 * to what that caller was trying to do ("Could not remove that host, try
 * again."), and must not be flattened into one generic sentence here.
 *
 * A 502 means Proxploy could not complete a call to Proxmox, not that
 * Proxploy itself is broken; read verbatim the passed-through text looks
 * like a Proxploy bug, so a 502's text alone gets a prefix that says whose
 * side failed. 4xx text is returned exactly as the backend wrote it.
 */
export function apiErrorDetail(e: unknown, fallback: string): string {
  if (!(e instanceof ApiError)) return fallback
  const detail = (e.body as { detail?: unknown } | null)?.detail
  const text = typeof detail === 'string' ? detail
    : typeof (detail as { detail?: unknown } | null)?.detail === 'string'
      ? (detail as { detail: string }).detail
      : undefined
  if (text == null) return fallback
  if (e.status === 502 && !text.startsWith('Proxmox')) return `Proxmox could not do this: ${text}`
  return text
}
