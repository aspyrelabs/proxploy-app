import { useEffect, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import { notify } from '../lib/notify'
import { useMe } from '../api/hooks'
import { inputCls } from './LoginForm'
import { Button } from './ui/button'
import { SkeletonLine } from './ui/skeleton'

const card = 'rounded-card border border-line-soft bg-panel p-5'
const label = 'mb-1 block text-[10.5px] uppercase tracking-wide text-text-3'

/**
 * Who you are on this installation: email, role, display name.
 *
 * `busy` is this card's own, not shared with the password form: saving a
 * display name has no business greying out "Set new password", and the two
 * calls hit different endpoints.
 */
export function AccountCard() {
  const { data: me, isPending: mePending } = useMe()
  const qc = useQueryClient()
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)

  // me arrives async; seed the field once it does, without clobbering an edit
  // already in progress.
  useEffect(() => { setName(n => n || me?.display_name || '') }, [me?.display_name])

  async function saveName() {
    if (!me) return
    // PATCH rejects a no-op body with 422, so don't send one.
    if (name === (me.display_name ?? '')) { notify.info('Display name unchanged.'); return }
    setBusy(true)
    try {
      await api(`/users/${me.id}`, { method: 'PATCH',
        body: JSON.stringify({ display_name: name }) })
      qc.invalidateQueries({ queryKey: ['me'] })
      notify.success('Display name updated.')
    } catch { notify.error('Could not update the display name.') } finally { setBusy(false) }
  }

  return (
    <section className={card}>
      <h2 className="mb-3 font-display text-[15px] font-semibold">Account</h2>
      <div className="grid gap-4 md:grid-cols-2">
        <div>
          <span className={label}>Email</span>
          {/* Both readouts print "unknown" for anything falsy, so during the
              /auth/me fetch the box is a claim about the reader's own account
              rather than a wait; same box either way, nothing moves. */}
          {/* A div, not a <p>: SkeletonLine renders a div and a div cannot
              legally nest inside a <p> -- React warned about exactly that in
              the loading state. Tailwind's preflight zeroes margin on both. */}
          <div className="rounded-ctl border border-line bg-panel-2 px-3 py-2 text-[13.5px] text-text-2">
            {mePending ? <SkeletonLine className="w-48 max-w-full text-[13.5px]" /> : me?.email ?? 'unknown'}
          </div>
          <p className="mt-1 text-[11.5px] text-text-3">
            The email cannot be changed after the account is created.
          </p>
        </div>
        <div>
          <span className={label}>Role</span>
          <div className="rounded-ctl border border-line bg-panel-2 px-3 py-2 font-mono text-[13px] text-text-2">
            {mePending ? <SkeletonLine className="w-20 text-[13px]" /> : me?.role ?? 'unknown'}
          </div>
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
    </section>
  )
}
