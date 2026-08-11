import { useEffect, useState } from 'react'
import { createRoute } from '@tanstack/react-router'
import { useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { shellRoute } from './shell'
import { api } from '../api/client'
import { useMe } from '../api/hooks'
import { inputCls } from '../components/LoginForm'
import { SessionsCard } from '../components/SessionsCard'
import { TotpCard } from '../components/TotpCard'
import { Button } from '../components/ui/button'

const card = 'rounded-card border border-line-soft bg-panel p-5'
const label = 'mb-1 block text-[10.5px] uppercase tracking-wide text-text-3'

/** The signed-in user's own account.
 *
 *  TotpCard and SessionsCard were already self-service, but they only existed
 *  inside Settings, next to fleet-wide admin controls. This is the page the
 *  avatar menu points at: your account, not the installation's. */
export function ProfilePage() {
  const { data: me } = useMe()
  const qc = useQueryClient()
  const [name, setName] = useState('')
  const [pw, setPw] = useState('')
  const [busy, setBusy] = useState(false)

  // me arrives async; seed the field once it does, without clobbering an edit
  // already in progress.
  useEffect(() => { setName(n => n || me?.display_name || '') }, [me?.display_name])

  async function saveName() {
    if (!me) return
    // PATCH rejects a no-op body with 422, so don't send one.
    if (name === (me.display_name ?? '')) { toast.info('Display name unchanged.'); return }
    setBusy(true)
    try {
      await api(`/users/${me.id}`, { method: 'PATCH',
        body: JSON.stringify({ display_name: name }) })
      qc.invalidateQueries({ queryKey: ['me'] })
      toast.success('Display name updated.')
    } catch { toast.error('Could not update the display name.') } finally { setBusy(false) }
  }

  async function savePassword() {
    if (!me) return
    setBusy(true)
    try {
      await api(`/users/${me.id}/password`, { method: 'POST',
        body: JSON.stringify({ password: pw }) })
      // The reset revokes every session, this one included (auth.py's own
      // note: an admin-set password is a recovery mechanism). Logging straight
      // back in is what stops this page signing you out of itself.
      await api('/auth/login', { method: 'POST',
        body: JSON.stringify({ email: me.email, password: pw }) })
      setPw('')
      toast.success('Password updated. Other sessions were signed out.')
    } catch { toast.error('Could not set the password (12+ characters).') } finally { setBusy(false) }
  }

  return (
    <div className="space-y-5">
      <div>
        <h1 className="font-display text-[22px] font-semibold">Profile and security</h1>
        <p className="mt-0.5 text-[12.5px] text-text-3">Your account on this installation.</p>
      </div>

      <div className={card}>
        <h2 className="mb-3 text-[13px] font-semibold text-text">Account</h2>
        <div className="grid gap-4 md:grid-cols-2">
          <div>
            <span className={label}>Email</span>
            <p className="rounded-ctl border border-line bg-panel-2 px-3 py-2 text-[13.5px] text-text-2">
              {me?.email ?? '—'}
            </p>
            <p className="mt-1 text-[11.5px] text-text-3">
              The email cannot be changed after the account is created.
            </p>
          </div>
          <div>
            <span className={label}>Role</span>
            <p className="rounded-ctl border border-line bg-panel-2 px-3 py-2 font-mono text-[13px] text-text-2">
              {me?.role ?? '—'}
            </p>
          </div>
        </div>

        <div className="mt-4 max-w-md">
          <label htmlFor="profile-name" className={label}>Display name</label>
          <input id="profile-name" className={inputCls} value={name}
            onChange={e => setName(e.target.value)} />
          <Button variant="ghost" className="mt-2" disabled={busy} onClick={saveName}>
            Save display name
          </Button>
        </div>
      </div>

      <div className={card}>
        <h2 className="mb-1 text-[13px] font-semibold text-text">Password</h2>
        <p className="mb-3 text-[12px] text-text-3">
          Changing it signs out every other session, including any you have forgotten about.
        </p>
        <div className="max-w-md">
          <label htmlFor="profile-pw" className={label}>New password (12+ chars)</label>
          <input id="profile-pw" type="password" className={inputCls} value={pw}
            onChange={e => setPw(e.target.value)} />
          <Button className="mt-2" disabled={busy || pw.length < 12} onClick={savePassword}>
            Set new password
          </Button>
        </div>
      </div>

      <TotpCard />
      <SessionsCard />
    </div>
  )
}

export const profileRoute = createRoute({
  getParentRoute: () => shellRoute,
  path: '/profile',
  component: ProfilePage,
})
