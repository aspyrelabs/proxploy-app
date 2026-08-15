import { useEffect, useState } from 'react'
import { api, apiErrorDetail, ApiError } from '../api/client'
import { fetchOnboarding } from '../api/account'
import { Button } from './ui/button'
import Logo from './Logo'

export const inputCls =
  'w-full rounded-ctl border border-line bg-panel px-3 py-2 text-[13.5px] text-text placeholder:text-text-3 focus:border-amber focus:outline-none'

// The real brand mark, replacing the gradient "P" tile and the Prox/ploy
// split that stood in for it. currentColor carries the amber, so this is the
// same artwork proxploy-web ships with no second copy of the colours.
export function Brand() {
  return <Logo className="h-[30px] w-auto text-amber" />
}

type LoginResult = { ok?: true; user?: unknown; totp_required?: true; pending?: string }

export function LoginForm({ onSuccess }: { onSuccess: () => void }) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [code, setCode] = useState('')
  const [pending, setPending] = useState<string | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [oidc, setOidc] = useState(false)

  // Plain effect + one-off fetch, not react-query: this page renders
  // pre-session (no QueryClientProvider guaranteed above it in every
  // caller/test) and needs nothing beyond "does the SSO button show".
  useEffect(() => { fetchOnboarding().then(o => setOidc(o.oidc)).catch(() => {}) }, [])

  async function submitPassword(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true); setError('')
    try {
      const r = await api<LoginResult>('/auth/login', {
        method: 'POST', body: JSON.stringify({ email, password }),
      })
      if (r.totp_required) setPending(r.pending!)
      else onSuccess()
    } catch (err) {
      // A non-401 ApiError means the server answered and said what was
      // wrong (a 422 validation error, most often); apiErrorDetail's
      // fallback only fires when the request itself never got a response,
      // which is the one case "is the server reachable?" is honest about.
      setError(err instanceof ApiError && err.status === 401
        ? 'Invalid email or password.'
        : apiErrorDetail(err, 'Sign-in failed, is the server reachable?'))
    } finally { setBusy(false) }
  }

  async function submitCode(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true); setError('')
    try {
      await api('/auth/totp', { method: 'POST', body: JSON.stringify({ pending, code }) })
      onSuccess()
    } catch {
      // Pending token is deliberately kept (not cleared): a wrong code
      // re-shows this same screen, matching the backend's attempt-capped
      // pending store, only 5 wrong guesses burn it, not 1 (Task 9).
      setError('That code was not accepted, try again or use a recovery code.')
    } finally { setBusy(false) }
  }

  if (pending) {
    return (
      <form onSubmit={submitCode} className="w-[360px] max-w-[92vw] rounded-card border border-line-soft bg-panel p-7 shadow-2xl">
        <div className="mb-6 flex justify-center"><Brand /></div>
        <label className="mb-1 block text-[11px] uppercase tracking-wide text-text-3" htmlFor="totp-code">Authentication code</label>
        <input id="totp-code" type="text" inputMode="numeric" autoComplete="one-time-code" autoFocus required
          value={code} onChange={e => setCode(e.target.value)} className={inputCls + ' mb-2'} />
        <p className="mb-4 text-[12px] text-text-3">Use a recovery code if you do not have your authenticator app.</p>
        {error && <p className="mb-3 text-[12.5px] text-red">{error}</p>}
        <Button type="submit" disabled={busy} className="w-full">{busy ? 'Verifying…' : 'Verify'}</Button>
      </form>
    )
  }

  return (
    <form onSubmit={submitPassword} className="w-[360px] max-w-[92vw] rounded-card border border-line-soft bg-panel p-7 shadow-2xl">
      <div className="mb-6 flex justify-center"><Brand /></div>
      <label className="mb-1 block text-[11px] uppercase tracking-wide text-text-3" htmlFor="email">Email</label>
      <input id="email" type="email" required value={email} onChange={e => setEmail(e.target.value)} className={inputCls + ' mb-4'} />
      <label className="mb-1 block text-[11px] uppercase tracking-wide text-text-3" htmlFor="password">Password</label>
      <input id="password" type="password" required value={password} onChange={e => setPassword(e.target.value)} className={inputCls + ' mb-5'} />
      {error && <p className="mb-3 text-[12.5px] text-red">{error}</p>}
      <Button type="submit" disabled={busy} className="w-full">{busy ? 'Signing in…' : 'Sign in'}</Button>
      {oidc && (
        <a href="/api/v1/auth/oidc/login"
          className="mt-3 block text-center text-[12.5px] text-text-2 underline-offset-2 hover:text-text hover:underline">
          Sign in with SSO
        </a>
      )}
    </form>
  )
}
