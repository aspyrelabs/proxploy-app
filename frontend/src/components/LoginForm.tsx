import { useState } from 'react'
import { api, ApiError } from '../api/client'
import { Button } from './ui/button'

export const inputCls =
  'w-full rounded-ctl border border-line bg-panel px-3 py-2 text-[13.5px] text-text placeholder:text-text-3 focus:border-amber focus:outline-none'

export function Brand() {
  return (
    <div className="flex items-center gap-2 font-display text-[17px] font-semibold">
      <span className="grid h-7 w-7 place-items-center rounded-tile bg-[linear-gradient(150deg,#F5B544,#E0862B)] text-[13px] font-bold text-[#20160a]">P</span>
      <span>Prox<b className="text-amber">ploy</b></span>
    </div>
  )
}

export function LoginForm({ onSuccess }: { onSuccess: () => void }) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true); setError('')
    try {
      await api('/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) })
      onSuccess()
    } catch (err) {
      setError(err instanceof ApiError && err.status === 401
        ? 'Invalid email or password.' : 'Sign-in failed — is the server reachable?')
    } finally { setBusy(false) }
  }

  return (
    <form onSubmit={submit} className="w-[360px] rounded-card border border-line-soft bg-panel p-7 shadow-2xl">
      <div className="mb-6 flex justify-center"><Brand /></div>
      <label className="mb-1 block text-[11px] uppercase tracking-wide text-text-3" htmlFor="email">Email</label>
      <input id="email" type="email" required value={email} onChange={e => setEmail(e.target.value)} className={inputCls + ' mb-4'} />
      <label className="mb-1 block text-[11px] uppercase tracking-wide text-text-3" htmlFor="password">Password</label>
      <input id="password" type="password" required value={password} onChange={e => setPassword(e.target.value)} className={inputCls + ' mb-5'} />
      {error && <p className="mb-3 text-[12.5px] text-red">{error}</p>}
      <Button type="submit" disabled={busy} className="w-full">{busy ? 'Signing in…' : 'Sign in'}</Button>
    </form>
  )
}
