import { useState } from 'react'
import { createRoute, redirect, useNavigate } from '@tanstack/react-router'
import { rootRoute } from '../router'
import { api } from '../api/client'
import { Brand, inputCls } from '../components/LoginForm'
import { HostForm, type HostCreated } from '../components/HostForm'
import { Button } from '../components/ui/button'

export const onboardingRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/onboarding',
  component: Wizard,
  beforeLoad: async () => {
    const ob = await api<{ complete: boolean }>('/meta/onboarding')
    // cast: circular import with router.tsx blocks full route-tree inference here
    if (ob.complete) throw redirect({ to: '/cluster' as never })
  },
})

const STEPS = ['Admin account', 'First host', 'Authorize installs', 'Done'] as const

function Wizard() {
  const navigate = useNavigate()
  const [step, setStep] = useState(0)
  const [host, setHost] = useState<HostCreated | null>(null)
  const [admin, setAdmin] = useState({ email: '', password: '', display_name: '' })
  const [error, setError] = useState('')

  async function createAdmin(e: React.FormEvent) {
    e.preventDefault(); setError('')
    try {
      await api('/users', { method: 'POST', body: JSON.stringify(admin) })
      await api('/auth/login', { method: 'POST',
        body: JSON.stringify({ email: admin.email, password: admin.password }) })
      setStep(1)
    } catch { setError('Could not create the admin account (password: 12+ characters).') }
  }

  async function finish() {
    await api('/settings', { method: 'PATCH',
      body: JSON.stringify({ 'onboarding.complete': true }) })
    navigate({ to: '/cluster' as never })
  }

  return (
    <div className="grid min-h-screen place-items-center">
      <div className="w-[520px] rounded-card border border-line-soft bg-panel p-7">
        <div className="mb-5 flex items-center justify-between">
          <Brand />
          <div className="flex gap-1.5">
            {STEPS.map((s, i) => (
              <span key={s} className={`rounded-full border px-2 py-0.5 font-mono text-[9.5px] ${i === step ? 'border-amber text-amber' : 'border-line text-text-3'}`}>{i + 1} {s}</span>
            ))}
          </div>
        </div>

        {step === 0 && (
          <form onSubmit={createAdmin} className="space-y-4">
            {([['email', 'Email', 'email'], ['display_name', 'Display name', 'text'],
               ['password', 'Password (12+ chars)', 'password']] as const).map(([k, label, type]) => (
              <div key={k}>
                <label htmlFor={k} className="mb-1 block text-[11px] uppercase tracking-wide text-text-3">{label}</label>
                <input id={k} type={type} required={k !== 'display_name'} className={inputCls}
                  value={admin[k]} onChange={e => setAdmin(a => ({ ...a, [k]: e.target.value }))} />
              </div>
            ))}
            {error && <p className="text-[12.5px] text-red">{error}</p>}
            <Button type="submit" className="w-full">Create admin account</Button>
          </form>
        )}

        {step === 1 && <HostForm onCreated={h => { setHost(h); setStep(h.ssh_public_key ? 2 : 3) }} />}

        {step === 2 && host?.authorized_keys_line && (
          <div className="space-y-3">
            <p className="text-[13px] text-text-2">{host.consent_note}</p>
            <pre className="overflow-x-auto rounded-ctl bg-[#0a0e14] p-3 font-mono text-[11.5px] leading-[1.7] text-text-2">{`echo '${host.authorized_keys_line}' >> /root/.ssh/authorized_keys`}</pre>
            <div className="flex gap-2">
              <Button variant="ghost" onClick={() => navigator.clipboard.writeText(host.authorized_keys_line!)}>Copy key line</Button>
              <Button onClick={() => setStep(3)}>I have authorized it</Button>
            </div>
          </div>
        )}

        {step === 3 && (
          <div className="space-y-4 text-center">
            <p className="text-[13.5px] text-text-2">
              {host ? `Host ${host.name} connected.` : 'Setup complete.'} Proxploy is ready.
            </p>
            <Button className="w-full" onClick={finish}>Open the dashboard</Button>
          </div>
        )}
      </div>
    </div>
  )
}
