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
  // Never for FormData: the browser has to set multipart/form-data itself so
  // it can put the boundary in, and an explicit Content-Type overwrites it.
  if (opts.body != null && !(opts.body instanceof FormData)) {
    headers['Content-Type'] = 'application/json'
  }
  if (MUTATING.has(method)) headers['X-CSRF-Token'] = cookie('pp_csrf')
  const r = await fetch('/api/v1' + path, { credentials: 'include', ...opts, method, headers })
  const body = r.status === 204 ? null : await r.json().catch(() => null)
  if (!r.ok) throw new ApiError(r.status, body)
  return body as T
}

/**
 * Shared funnel from a caught ApiError to text. FastAPI wraps a route's
 * raise as `HTTPException(status, X)` → `{"detail": X}`, where X is a plain
 * string or, at the ~20 sites that raise 502 when a Proxmox call fails, an
 * object `{"error": <kind>, "detail": <text>}`. `detail` also arrives as an
 * ARRAY of `{loc, msg, type, ...}` for FastAPI 422 validation errors, and as
 * a plain string in RFC 9457 problem+json responses.
 *
 * `fallback` is caller-supplied user-facing copy (specific to what that
 * caller was doing) and must not be flattened into one generic sentence.
 *
 * A 502 means Proxmox (not Proxploy) failed; its text alone gets the prefix
 * "Proxmox could not do this:". 4xx text is returned exactly as written.
 */
function detailText(detail: unknown): string | undefined {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    const msgs = detail
      .map((d) => (typeof d === 'object' && d !== null && typeof (d as { msg?: unknown }).msg === 'string'
        ? (d as { msg: string }).msg : null))
      .filter((m): m is string => m != null)
    return msgs.length > 0 ? msgs.join('; ') : undefined
  }
  if (typeof detail === 'object' && detail !== null && typeof (detail as { detail?: unknown }).detail === 'string') {
    return (detail as { detail: string }).detail
  }
  return undefined
}

export function apiErrorDetail(e: unknown, fallback: string): string {
  if (!(e instanceof ApiError)) return fallback
  const text = detailText((e.body as { detail?: unknown } | null)?.detail)
  if (text == null) return fallback
  if (e.status === 502 && !text.startsWith('Proxmox')) return `Proxmox could not do this: ${text}`
  return text
}
