import { useState } from 'react'
import { createRoute, redirect, useNavigate } from '@tanstack/react-router'
import { useQuery, useQueryClient } from '@tanstack/react-query'
// shellRoute's sibling routes import rootRoute from ./shell, never ../router
//, importing router.tsx here would force its eager createRouter() to run
// mid-cycle (cluster.tsx and storage.tsx carry the same note).
import { rootRoute } from './shell'
import { api, ApiError } from '../api/client'
import { Brand, inputCls } from '../components/LoginForm'
import { HostForm, type HostCreated } from '../components/HostForm'
import { Button } from '../components/ui/button'
import { OnboardingRail, type RailStep } from '../components/OnboardingRail'

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

type Onboarding = { admin_exists: boolean; host_added: boolean
                    ssh_pending: boolean; complete: boolean }
type HostDetail = { id: number; name: string
                    credentials: { kind: string; public_meta: string | null }[] }
type MeOut = { id: number; email: string; display_name: string }

/** Server state decides where you are; the local override only ever moves
 *  you forward within one session, so a reload re-derives instead of
 *  restarting. This is the fix for "you already created the admin" being
 *  reported as "your password is bad". */
function stepFrom(ob: Onboarding): number {
  if (!ob.admin_exists) return 0
  if (!ob.host_added) return 1
  if (ob.ssh_pending) return 2
  return 3
}

export function Wizard() {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const ob = useQuery({ queryKey: ['onboarding'], queryFn: () => api<Onboarding>('/meta/onboarding') })
  // `serverStep` is where setup actually is; `view` is what is on screen and
  // is the only one of the two that may move backwards. Keeping them apart is
  // what makes Back possible without pretending a committed step can be undone.
  const serverStep = ob.data ? stepFrom(ob.data) : 0
  const [view, setView] = useState<number | null>(null)
  const [skipped, setSkipped] = useState(false)
  const step = view ?? serverStep
  const [dir, setDir] = useState<1 | -1>(1)
  const [host, setHost] = useState<HostCreated | null>(null)
  const [admin, setAdmin] = useState({ email: '', password: '', display_name: '' })
  const [error, setError] = useState('')
  const [verifyError, setVerifyError] = useState('')

  const me = useQuery({ queryKey: ['me'], queryFn: () => api<MeOut>('/auth/me'),
    enabled: !!ob.data?.admin_exists })

  function go(n: number) {
    setDir(n >= step ? 1 : -1)
    setView(n)
  }

  // Reload re-derives from the server instead of restarting, so a local
  // "advance" is always paired with invalidating the query it overrides.
  function advance(n: number) {
    setDir(1)
    setView(n)
    qc.invalidateQueries({ queryKey: ['onboarding'] })
  }

  // Status comes from the server, never from what was clicked, so a green tick
  // always means the server agrees the step is done.
  const done = [
    !!ob.data?.admin_exists,
    !!ob.data?.host_added,
    !!ob.data?.host_added && !ob.data?.ssh_pending,
    false,
  ]

  const railSteps: RailStep[] = STEPS.map((label, i) => {
    const status: RailStep['status'] =
      i === step ? 'current'
        : done[i] ? 'done'
          : skipped && (i === 1 || i === 2) ? 'skipped'
            : 'todo'
    const detail = i === 0 && done[0] ? me.data?.email
      : status === 'skipped' ? 'Skipped'
        : undefined
    // Reachable means "clicking this does something": anything already done,
    // anything skipped (so changing your mind costs one click), and the step
    // the server is on. Never a step in front of the server.
    return { label, status, detail,
             reachable: done[i] || status === 'skipped' || i === step || i <= serverStep }
  })

  // authorized_keys_line is only ever returned once, from POST /hosts. A
  // reload lands here with `host` null, the only way back to that line is
  // the ssh_key credential's public_meta, which is the same string.
  const needStoredHost = step === 2 && !host
  const storedHost = useQuery({
    queryKey: ['onboarding-host'],
    queryFn: async () => {
      const hosts = await api<{ id: number }[]>('/hosts')
      return hosts[0] ? api<HostDetail>(`/hosts/${hosts[0].id}`) : null
    },
    enabled: needStoredHost,
  })
  const hostId = host?.id ?? storedHost.data?.id
  const sshKeyLine = host?.authorized_keys_line
    ?? storedHost.data?.credentials.find(c => c.kind === 'ssh_key')?.public_meta
    ?? null

  async function verifySsh() {
    setVerifyError('')
    try {
      // Don't wait on the storedHost query's own timing, the id it would
      // supply is one more fetch away either way, and this can't run before
      // ssh_pending said a host exists.
      const id = hostId ?? (await api<{ id: number }[]>('/hosts'))[0]?.id
      if (id == null) throw new Error('no host to verify')
      await api(`/hosts/${id}/ssh/verify`, { method: 'POST' })
      advance(3)
    } catch (e) {
      // A mis-pasted key used to surface at the first app install instead of
      // here, far from its cause. host_key_mismatch is a security event, 
      // everything else just means "not authorized yet".
      setVerifyError(e instanceof ApiError && (e.body as any)?.error === 'host_key_mismatch'
        ? "The node's SSH host key changed since Proxploy first saw it. Stop and investigate."
        : 'Not authorized yet, Proxploy still cannot open a root shell on the node. '
          + 'Check the line was added to /root/.ssh/authorized_keys and saved.')
    }
  }

  async function createAdmin(e: React.FormEvent) {
    e.preventDefault(); setError('')
    try {
      await api('/users', { method: 'POST', body: JSON.stringify(admin) })
      await api('/auth/login', { method: 'POST',
        body: JSON.stringify({ email: admin.email, password: admin.password }) })
      advance(1)
    } catch { setError('Could not create the admin account (password: 12+ characters).') }
  }

  async function finish() {
    await api('/settings', { method: 'PATCH',
      body: JSON.stringify({ 'onboarding.complete': true }) })
    navigate({ to: '/cluster' as never })
  }

  return (
    <div className="flex min-h-screen flex-col md:flex-row">
      <aside className="shrink-0 border-b border-line bg-panel px-5 py-4
                        md:w-[152px] md:border-b-0 md:border-r md:py-6">
        <Brand />
        <p className="mb-4 mt-1 text-[9px] uppercase tracking-wide text-text-3 md:mb-5">
          Setup · {Math.min(step + 1, STEPS.length)} of {STEPS.length}
        </p>
        <OnboardingRail steps={railSteps} view={step} onSelect={go} />
      </aside>

      <main className="grid flex-1 place-items-center px-5 py-8">
        <div key={step} className={`w-full max-w-[380px] ${dir === 1 ? 'pp-in-fwd' : 'pp-in-back'}`}>
          {step > 0 && (
            <button type="button" onClick={() => go(step - 1)}
              className="mb-3 cursor-pointer text-[12px] text-text-3 transition hover:text-text-2">
              ← Back
            </button>
          )}

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

        {step === 1 && (
          <div className="space-y-3">
            <HostForm onCreated={h => { setHost(h); advance(h.ssh_public_key ? 2 : 3) }} />
            <Button variant="ghost" onClick={() => { setSkipped(true); advance(3) }}>Skip for now</Button>
            <p className="text-[12px] text-text-3">
              You can add a host later from Settings. Everything except managing nodes works without one.
            </p>
          </div>
        )}

        {step === 2 && (
          <div className="space-y-3">
            <p className="text-[13px] text-text-2">
              {host?.consent_note ?? 'A key was enrolled for this host. Add it to '
                + '/root/.ssh/authorized_keys on the node, then verify below.'}
            </p>
            {sshKeyLine && (
              <pre className="overflow-x-auto rounded-ctl bg-[#0a0e14] p-3 font-mono text-[11.5px] leading-[1.7] text-text-2">{`echo '${sshKeyLine}' >> /root/.ssh/authorized_keys`}</pre>
            )}
            {verifyError && <p className="text-[12.5px] text-red">{verifyError}</p>}
            <div className="flex gap-2">
              {sshKeyLine && (
                <Button variant="ghost" onClick={() => navigator.clipboard.writeText(sshKeyLine)}>Copy key line</Button>
              )}
              <Button onClick={verifySsh}>Verify access</Button>
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
      </main>
    </div>
  )
}
