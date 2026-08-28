import { useState } from 'react'
import { ApiError, api, apiErrorDetail } from '../api/client'
import { Button } from './ui/button'
import { Dialog } from './ui/dialog'
import { Icon } from './ui/icon'
import { inputCls } from './LoginForm'
import { PasswordStrength } from './PasswordStrength'
import { refusal } from '../lib/password-strength'

/**
 * Set a new password by spending a two-factor recovery code.
 *
 * A recovery code is the only proof this flow accepts. There is deliberately
 * no email link: whoever reads that inbox would get the hypervisor with it.
 * An account that never enrolled two-factor therefore has no way back from
 * here, which the copy says plainly rather than letting someone type an
 * address and wait for a mail that is never coming.
 */
export function RecoverDialog({ email: initial, onClose, onDone }: {
  email?: string; onClose: () => void; onDone: () => void
}) {
  const [email, setEmail] = useState(initial ?? '')
  const [code, setCode] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const label = 'mb-1 block text-[11px] uppercase tracking-wide text-text-3'

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true); setError('')
    try {
      await api('/auth/recover', {
        method: 'POST',
        body: JSON.stringify({ email, recovery_code: code.trim(), password }),
      })
      onDone()
    } catch (err) {
      setError(err instanceof ApiError && err.status === 401
        ? 'That recovery code is not valid for this account. Recovery codes only '
          + 'exist for accounts with two-factor turned on.'
        : apiErrorDetail(err, 'Could not set the password, is the server reachable?'))
    } finally { setBusy(false) }
  }

  return (
    <Dialog width={560} onClose={onClose}
      title={
        <span className="flex min-w-0 items-center gap-2.5">
          <span className="grid size-8 shrink-0 place-items-center rounded-tile
                           border border-line bg-panel-2 text-amber">
            <Icon name="shield" size={18} />
          </span>
          <span className="flex min-w-0 flex-col leading-tight">
            <span className="truncate">Use a recovery code</span>
            <span className="truncate font-mono text-[11px] font-normal text-text-3">
              two-factor · the only way back
            </span>
          </span>
        </span>}>
      <form onSubmit={submit} className="mt-4 space-y-3">
        <div className="space-y-3 rounded-card border border-line-soft bg-panel-2 p-4">
          <div>
            <label className={label} htmlFor="rc-email">Email</label>
            <input id="rc-email" type="email" required className={inputCls}
              value={email} onChange={(e) => setEmail(e.target.value)} />
          </div>
          <div>
            <label className={label} htmlFor="rc-code">Recovery code</label>
            <input id="rc-code" required className={inputCls} autoComplete="off"
              placeholder="one of the codes saved when two-factor was set up"
              value={code} onChange={(e) => setCode(e.target.value)} />
          </div>
          <div>
            <label className={label} htmlFor="rc-pw">New password</label>
            <input id="rc-pw" type="password" required className={inputCls}
              value={password} onChange={(e) => setPassword(e.target.value)} />
            <PasswordStrength value={password} email={email} />
          </div>
        </div>

        <div className="rounded-ctl border border-line-soft bg-elev p-3">
          <p className="text-[12px] text-text-2">
            The code is spent once used, this signs out every session, and every
            device trusted to skip the second factor loses that trust. If the
            account never had two-factor turned on, nothing here can recover it
            and an administrator has to set the password.
          </p>
        </div>

        {error && <p className="text-[12.5px] text-red">{error}</p>}

        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
          <Button type="submit" variant="primary"
            disabled={busy || !code.trim() || refusal(password) !== null}>
            {busy ? 'Setting…' : 'Set new password'}
          </Button>
        </div>
      </form>
    </Dialog>
  )
}
