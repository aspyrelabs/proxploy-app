import { useState } from 'react'
import { api } from '../api/client'
import { inputCls } from './LoginForm'
import { Button } from './ui/button'

type Existing = { id: number; email: string; display_name: string }

// Mirrors UserIn.password / PasswordResetIn in backend/proxploy/api/auth.py.
// The server is still the authority; this is so the form stops claiming a
// minimum it does not check, and stops sending requests it knows will 422.
const MIN_PASSWORD = 12

/** Step 1 of onboarding, in both of its modes.
 *
 *  `existing === null` is a fresh install and renders the create form. Once the
 *  account exists the step is still reachable from the rail, but what it can
 *  offer is bounded by the API: the display name and the password can be
 *  changed, the email cannot. */
export function AdminAccountStep({ existing, onCreated }: {
  existing: Existing | null
  onCreated: () => void
}) {
  const [admin, setAdmin] = useState({ email: '', password: '', display_name: '' })
  const [error, setError] = useState('')
  // Creating the account is the first irreversible thing onboarding does, and
  // the email it burns in cannot be changed afterwards. So the form commits to
  // a local review screen first, and only the review screen calls POST /users.
  const [reviewing, setReviewing] = useState(false)

  // minLength above is the browser's affordance; this is the one that actually
  // gates, because jsdom and any programmatic submit skip native validation.
  function review(e: React.FormEvent) {
    e.preventDefault(); setError('')
    if (admin.password.length < MIN_PASSWORD) {
      setError(`Password must be at least ${MIN_PASSWORD} characters.`)
      return
    }
    setReviewing(true)
  }

  async function createAdmin() {
    setError('')
    try {
      await api('/users', { method: 'POST', body: JSON.stringify(admin) })
      await api('/auth/login', { method: 'POST',
        body: JSON.stringify({ email: admin.email, password: admin.password }) })
      onCreated()
    } catch {
      setReviewing(false)
      setError('Could not create the admin account (password: 12+ characters).')
    }
  }

  if (existing) return <EditPanel existing={existing} />

  if (reviewing) return (
    <div className="space-y-4">
      <Heading title="Check this over"
        sub="Nothing has been created yet. The email is the one thing you cannot change afterwards." />
      <dl className="divide-y divide-line rounded-ctl border border-line bg-panel-2 px-3">
        {([['Email', admin.email], ['Display name', admin.display_name || 'not set'],
           ['Password', '•'.repeat(Math.min(admin.password.length, 16))]] as const).map(([k, v]) => (
          <div key={k} className="flex items-baseline justify-between gap-3 py-2">
            <dt className="text-[11px] uppercase tracking-wide text-text-3">{k}</dt>
            <dd className="truncate text-[13px] text-text">{v}</dd>
          </div>
        ))}
      </dl>
      {error && <p className="text-[12.5px] text-red">{error}</p>}
      <div className="flex gap-2">
        <Button variant="ghost" onClick={() => setReviewing(false)}>Change details</Button>
        <Button className="flex-1" onClick={createAdmin}>Create account</Button>
      </div>
    </div>
  )

  return (
    <form onSubmit={review} className="space-y-4">
      <Heading title="Create your admin account"
        sub="This is the account you will sign in with. You get to check it before anything is created." />
      {([['email', 'Email', 'email'], ['display_name', 'Display name', 'text'],
         ['password', 'Password (12+ chars)', 'password']] as const).map(([k, label, type]) => (
        <div key={k}>
          <label htmlFor={k} className="mb-1 block text-[11px] uppercase tracking-wide text-text-3">{label}</label>
          <input id={k} type={type} required={k !== 'display_name'} className={inputCls}
            minLength={k === 'password' ? MIN_PASSWORD : undefined}
            value={admin[k]} onChange={e => setAdmin(a => ({ ...a, [k]: e.target.value }))} />
        </div>
      ))}
      {error && <p className="text-[12.5px] text-red">{error}</p>}
      <Button type="submit" className="w-full">Review</Button>
    </form>
  )
}

function Heading({ title, sub }: { title: string; sub: string }) {
  return (
    <div>
      <h1 className="text-[15px] font-semibold text-text">{title}</h1>
      <p className="mt-0.5 text-[12px] text-text-3">{sub}</p>
    </div>
  )
}

function EditPanel({ existing }: { existing: Existing }) {
  const [name, setName] = useState(existing.display_name ?? '')
  const [pw, setPw] = useState('')
  const [note, setNote] = useState('')
  const [error, setError] = useState('')

  async function saveName() {
    setError(''); setNote('')
    // PATCH rejects a no-op body with 422, so skip the call when nothing moved.
    if (name === existing.display_name) { setNote('Display name unchanged.'); return }
    try {
      await api(`/users/${existing.id}`, { method: 'PATCH',
        body: JSON.stringify({ display_name: name }) })
      setNote('Display name updated.')
    } catch { setError('Could not update the display name.') }
  }

  async function savePassword() {
    setError(''); setNote('')
    try {
      await api(`/users/${existing.id}/password`, { method: 'POST',
        body: JSON.stringify({ password: pw }) })
      // The reset revokes every session, this one included. Logging straight
      // back in is what stops the wizard dropping you at the login screen.
      await api('/auth/login', { method: 'POST',
        body: JSON.stringify({ email: existing.email, password: pw }) })
      setPw(''); setNote('Password updated.')
    } catch { setError('Could not set the password (12+ characters).') }
  }

  return (
    <div className="space-y-4">
      <Heading title="Your admin account" sub="Created already, so some of it is now fixed." />

      <div>
        <span className="mb-1 block text-[11px] uppercase tracking-wide text-text-3">Email</span>
        <p className="rounded-ctl border border-line bg-panel-2 px-3 py-2 text-[13.5px] text-text-2">
          {existing.email}
        </p>
        <p className="mt-1 text-[11.5px] text-text-3">
          The email cannot be changed once the account exists. Create a second
          account from Settings if you need a different one.
        </p>
      </div>

      <div>
        <label htmlFor="edit-name" className="mb-1 block text-[11px] uppercase tracking-wide text-text-3">
          Display name
        </label>
        <input id="edit-name" className={inputCls} value={name}
          onChange={e => setName(e.target.value)} />
      </div>

      <div>
        <label htmlFor="edit-pw" className="mb-1 block text-[11px] uppercase tracking-wide text-text-3">
          New password
        </label>
        <input id="edit-pw" type="password" className={inputCls} value={pw}
          onChange={e => setPw(e.target.value)} />
      </div>

      {note && <p className="text-[12.5px] text-green">{note}</p>}
      {error && <p className="text-[12.5px] text-red">{error}</p>}

      <div className="flex gap-2">
        <Button variant="ghost" onClick={saveName}>Save display name</Button>
        <Button onClick={savePassword} disabled={pw.length < MIN_PASSWORD}>Set new password</Button>
      </div>
    </div>
  )
}
