import { useState } from 'react'
import { createRoute, redirect, useNavigate } from '@tanstack/react-router'
import { useQuery, useQueryClient } from '@tanstack/react-query'
// shellRoute's sibling routes import rootRoute from ./shell, never ../router
//, importing router.tsx here would force its eager createRouter() to run
// mid-cycle (cluster.tsx and storage.tsx carry the same note).
import { rootRoute } from './shell'
import { api, ApiError } from '../api/client'
import { Brand } from '../components/LoginForm'
import { AdminAccountStep } from '../components/AdminAccountStep'
import { HostForm, type HostCreated } from '../components/HostForm'
import { HostRemoveDialog } from '../components/HostRemoveDialog'
import { Button } from '../components/ui/button'
import { Loading } from '../components/ui/loading'
import { Skeleton, SkeletonGroup, SkeletonLine } from '../components/ui/skeleton'
import { StepRail, type RailStep } from '../components/StepRail'

export const onboardingRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/onboarding',
  component: Wizard,
  beforeLoad: async () => {
    const ob = await api<{ complete: boolean }>('/meta/onboarding')
    // cast: circular import with router.tsx blocks full route-tree inference here
    if (ob.complete) throw redirect({ to: '/hosts' as never })
  },
})

const STEPS = ['Account', 'Host', 'Install', 'Verify', 'Self', 'Done'] as const

// Index names, because six bare numbers scattered through the component is
// how off-by-one bugs get in.
const S_ACCOUNT = 0, S_HOST = 1, S_INSTALL = 2, S_VERIFY = 3, S_SELF = 4, S_DONE = 5

type Onboarding = { admin_exists: boolean; host_added: boolean
                    ssh_pending: boolean; complete: boolean }
type HostDetail = { id: number; name: string
                    credentials: { kind: string; public_meta: string | null }[] }
type MeOut = { id: number; email: string; display_name: string }

/** Server state decides where you are; the local override only ever moves
 *  you forward within one session, so a reload re-derives instead of
 *  restarting. This is the fix for "you already created the admin" being
 *  reported as "your password is bad".
 *
 *  Install and Verify both sit on `ssh_pending`: the server cannot tell "the
 *  operator has pasted the key" from "they have not", only whether the key
 *  works. So `stepFrom` lands on Install, and moving to Verify is a local
 *  acknowledgement. Both tick green together when ssh_pending flips false,
 *  which is the one thing the server does know.
 *
 *  `selfAnswered` comes from GET /settings (self.host_id is a present key,
 *  regardless of its value, once answered; see SelfHostStep). Only checked
 *  once a host actually exists: with none enrolled the honest answer is
 *  already "none of these" for free, nothing to ask (PXP-33). */
function stepFrom(ob: Onboarding, selfAnswered: boolean): number {
  if (!ob.admin_exists) return S_ACCOUNT
  if (!ob.host_added) return S_HOST
  if (ob.ssh_pending) return S_INSTALL
  if (!selfAnswered) return S_SELF
  return S_DONE
}

export function Wizard() {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const ob = useQuery({ queryKey: ['onboarding'], queryFn: () => api<Onboarding>('/meta/onboarding') })
  // Only fetched once a host exists: with none enrolled the Self step is
  // never reached (stepFrom short-circuits on !host_added first), so there is
  // nothing here worth a key to be "answered".
  const settingsQ = useQuery({
    queryKey: ['settings'],
    queryFn: () => api<Record<string, unknown>>('/settings'),
    enabled: !!ob.data?.host_added,
  })
  const selfAnswered = settingsQ.data != null
    && Object.prototype.hasOwnProperty.call(settingsQ.data, 'self.host_id')
  // `serverStep` is where setup actually is; `view` is what is on screen and
  // is the only one of the two that may move backwards. Keeping them apart is
  // what makes Back possible without pretending a committed step can be undone.
  const serverStep = ob.data ? stepFrom(ob.data, selfAnswered) : 0
  const [view, setView] = useState<number | null>(null)
  const [skipped, setSkipped] = useState(false)
  const step = view ?? serverStep
  const [dir, setDir] = useState<1 | -1>(1)
  const [host, setHost] = useState<HostCreated | null>(null)
  const [removing, setRemoving] = useState(false)
  const [verifyError, setVerifyError] = useState('')
  const [verifying, setVerifying] = useState(false)
  const [savingSelf, setSavingSelf] = useState(false)

  const me = useQuery({ queryKey: ['me'], queryFn: () => api<MeOut>('/auth/me'),
    enabled: !!ob.data?.admin_exists })
  // The Self step offers every enrolled host, not only the one this wizard
  // run just added: an install can already have several by the time this
  // step is reached (e.g. peers enrolled between sessions).
  const allHosts = useQuery({
    queryKey: ['onboarding-hosts-list'],
    queryFn: () => api<{ id: number; name: string }[]>('/hosts'),
    enabled: step === S_SELF,
  })

  async function saveSelfHost(hostId: number | null) {
    setSavingSelf(true)
    try {
      await api('/hosts/self', { method: 'PUT', body: JSON.stringify({ host_id: hostId }) })
      qc.invalidateQueries({ queryKey: ['settings'] })
      advance(S_DONE)
    } catch {
      // Left on the step; the select stays interactive to try again.
    } finally {
      setSavingSelf(false)
    }
  }

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

  // authorized_keys_line is only ever returned once, from POST /hosts. A
  // reload lands here with `host` null, the only way back to that line is
  // the ssh_key credential's public_meta, which is the same string.
  const storedHost = useQuery({
    queryKey: ['onboarding-host'],
    queryFn: async () => {
      const hosts = await api<{ id: number }[]>('/hosts')
      return hosts[0] ? api<HostDetail>(`/hosts/${hosts[0].id}`) : null
    },
    enabled: !!ob.data?.host_added && !host,
  })
  const hostId = host?.id ?? storedHost.data?.id
  const storedHostName = host?.name ?? storedHost.data?.name ?? null
  const sshKeyLine = host?.authorized_keys_line
    ?? storedHost.data?.credentials.find(c => c.kind === 'ssh_key')?.public_meta
    ?? null
  // One value behind both the <pre> and the copy button. They used to be built
  // separately, so the screen showed a shell command while the button copied
  // the bare key, and what the operator pasted was not what they had been told
  // to run.
  const authorizeCommand = sshKeyLine
    ? `echo '${sshKeyLine}' >> /root/.ssh/authorized_keys`
    : null

  // Status comes from the server, never from what was clicked, so a green tick
  // always means the server agrees the step is done.
  const sshDone = !!ob.data?.host_added && !ob.data?.ssh_pending
  const done = [
    !!ob.data?.admin_exists,
    !!ob.data?.host_added,
    sshDone,
    sshDone,
    selfAnswered,
    false,
  ]

  const railSteps: RailStep[] = STEPS.map((label, i) => {
    const status: RailStep['status'] =
      i === step ? 'current'
        : done[i] ? 'done'
          : skipped && i >= S_HOST && i <= S_SELF ? 'skipped'
            : 'todo'
    const detail = i === S_ACCOUNT && done[S_ACCOUNT] ? me.data?.email
      : i === S_HOST && done[S_HOST] ? storedHostName ?? undefined
        : status === 'skipped' ? 'Skipped'
          : undefined
    // Reachable means "clicking this does something": anything already done,
    // anything skipped (so changing your mind costs one click), and the step
    // the server is on. Never a step in front of the server.
    return { label, status, detail,
             reachable: done[i] || status === 'skipped' || i === step || i <= serverStep }
  })

  async function verifySsh() {
    setVerifyError('')
    setVerifying(true)
    try {
      // Don't wait on the storedHost query's own timing, the id it would
      // supply is one more fetch away either way, and this can't run before
      // ssh_pending said a host exists.
      const id = hostId ?? (await api<{ id: number }[]>('/hosts'))[0]?.id
      if (id == null) throw new Error('no host to verify')
      await api(`/hosts/${id}/ssh/verify`, { method: 'POST' })
      advance(selfAnswered ? S_DONE : S_SELF)
    } catch (e) {
      // A mis-pasted key used to surface at the first app install instead of
      // here, far from its cause. host_key_mismatch is a security event,
      // everything else just means "not authorized yet".
      setVerifyError(e instanceof ApiError && (e.body as any)?.error === 'host_key_mismatch'
        ? "The node's SSH host key changed since Proxploy first saw it. Stop and investigate."
        : 'Not authorized yet, Proxploy still cannot open a root shell on the node. '
          + 'Check the line was added to /root/.ssh/authorized_keys and saved.')
    } finally {
      setVerifying(false)
    }
  }

  async function finish() {
    await api('/settings', { method: 'PATCH',
      body: JSON.stringify({ 'onboarding.complete': true }) })
    navigate({ to: '/hosts' as never })
  }

  return (
    <div className="grid min-h-screen place-items-center px-5 py-8">
      <div className="flex w-full max-w-[820px] flex-col overflow-hidden rounded-card
                      border border-line-soft bg-panel md:flex-row">
        {/* 224px, not the 176px this started at: the lockup renders ~168px
            wide at its native 30px height, so anything narrower makes it
            overhang the divider. */}
        <aside className="shrink-0 border-b border-line bg-panel-2 px-5 py-5
                          md:w-[224px] md:border-b-0 md:border-r">
          <Brand />
          <p className="mb-4 mt-1.5 text-[9px] uppercase tracking-wide text-text-3 md:mb-5">
            Setup · {Math.min(step + 1, STEPS.length)} of {STEPS.length}
          </p>
          <StepRail steps={railSteps} view={step} onSelect={go} />
        </aside>

        <main className="min-w-0 flex-1 p-7">
          <div key={step} className={dir === 1 ? 'pp-in-fwd' : 'pp-in-back'}>
            {step > 0 && (
              <button type="button" onClick={() => go(step - 1)}
                className="mb-3 cursor-pointer text-[12px] text-text-3 transition hover:text-text-2">
                ← Back
              </button>
            )}

        {step === S_ACCOUNT && (
          // An admin that exists but no /auth/me means the session died. Showing
          // the create form here would POST /users for an account that already
          // exists and surface as "your password is bad", which is exactly the
          // confusion stepFrom() was written to kill.
          ob.data?.admin_exists && !me.data ? (
            // While /auth/me is in flight `!me.data` is true, so this branch
            // is the one that renders, and it used to render nothing at all:
            // the setup pane went blank between the rail and the Back link
            // for the length of that fetch. Which panel wins is not known yet
            // (a live session goes to AdminAccountStep instead), so this is
            // deliberately the shape both share, a heading over a short
            // paragraph over one control, and nothing more specific than that.
            me.isPending ? (
              <SkeletonGroup label="Checking your session" className="space-y-3">
                <SkeletonLine className="w-56 text-[15px]" />
                <div>
                  <SkeletonLine className="w-full text-[12.5px]" />
                  <SkeletonLine className="w-full text-[12.5px]" />
                  <SkeletonLine className="w-2/3 text-[12.5px]" />
                </div>
                <Skeleton className="h-[35px] w-32 rounded-ctl" />
              </SkeletonGroup>
            ) : (
              <div className="space-y-3">
                <h1 className="text-[15px] font-semibold text-text">You are signed out</h1>
                <p className="text-[12.5px] text-text-2">
                  The admin account already exists, but this browser is no longer
                  signed in, so it cannot be shown or changed here. Sign in to pick
                  setup back up.
                </p>
                <Button onClick={() => navigate({ to: '/login' as never })}>Go to sign in</Button>
              </div>
            )
          ) : (
            <AdminAccountStep
              existing={ob.data?.admin_exists && me.data ? me.data : null}
              onCreated={() => advance(S_HOST)}
            />
          )
        )}

        {step === S_HOST && (
          ob.data?.host_added ? (
            <div className="space-y-3">
              <h1 className="text-[15px] font-semibold text-text">Your first host</h1>
              <p className="text-[12.5px] text-text-2">
                {storedHostName ?? 'A host'} is connected. Its address and API token
                cannot be edited in place, so correcting either one means removing
                the host and adding it again.
              </p>
              <Button variant="danger" onClick={() => setRemoving(true)}>Remove and re-add</Button>
              {removing && hostId != null && (
                <HostRemoveDialog
                  hostId={hostId}
                  hostName={storedHostName ?? ''}
                  onClose={() => setRemoving(false)}
                  onRemoved={() => {
                    setRemoving(false); setHost(null)
                    qc.invalidateQueries({ queryKey: ['onboarding'] })
                    qc.invalidateQueries({ queryKey: ['onboarding-host'] })
                  }}
                />
              )}
            </div>
          ) : (
            <div className="space-y-3">
              {/* selfAnswered is never true here: this branch only ever runs
                  the FIRST time a host is added (host_added was still false),
                  and there is no way to have answered which host is "self"
                  before any host existed to pick, so S_SELF unconditionally
                  follows a keyless host, same as S_INSTALL does for one with
                  a key. */}
              <HostForm onCreated={h => { setHost(h); advance(h.ssh_public_key ? S_INSTALL : S_SELF) }} />
              <Button variant="ghost" onClick={() => { setSkipped(true); advance(S_DONE) }}>Skip for now</Button>
              <p className="text-[12px] text-text-3">
                You can add a host later from Settings. Everything except managing nodes works without one.
              </p>
            </div>
          )
        )}

        {step === S_INSTALL && (
          <div className="space-y-3">
            <h1 className="text-[15px] font-semibold text-text">Authorize installs</h1>
            <p className="text-[13px] text-text-2">
              {host?.consent_note ?? 'A key was enrolled for this host. Add it to '
                + '/root/.ssh/authorized_keys on the node, then verify on the next step.'}
            </p>
            {authorizeCommand && (
              <pre className="overflow-x-auto rounded-ctl bg-[#0a0e14] p-3 font-mono text-[11.5px] leading-[1.7] text-text-2">{authorizeCommand}</pre>
            )}
            <div className="flex gap-2">
              {authorizeCommand && (
                <Button variant="ghost" onClick={() => navigator.clipboard.writeText(authorizeCommand)}>Copy command</Button>
              )}
              <Button onClick={() => go(S_VERIFY)}>I have added it</Button>
            </div>
          </div>
        )}

        {step === S_VERIFY && (
          <div className="space-y-3">
            <h1 className="text-[15px] font-semibold text-text">Verify access</h1>
            <p className="text-[13px] text-text-2">
              Proxploy will open a root shell on {storedHostName ?? 'the node'} using
              the key you just added. Nothing is installed by this check.
            </p>
            {verifyError && <p className="text-[12.5px] text-red">{verifyError}</p>}
            <div className="flex items-center gap-2">
              <Button onClick={verifySsh} disabled={verifying}>Verify access</Button>
              {/* Nothing on this path calls ctx.progress(), opening a root
                  shell either works or it does not, so this is the ring, not
                  a number pretending to know how far along it is. */}
              {verifying && <Loading label="Verifying access" size={18} />}
            </div>
          </div>
        )}

        {step === S_SELF && (
          <div className="space-y-3">
            <h1 className="text-[15px] font-semibold text-text">Which host is this?</h1>
            <p className="text-[13px] text-text-2">
              If Proxploy itself runs on one of the hosts it manages, picking it
              here lets a reboot or power off warn before it cuts Proxploy off
              from itself. Not every install does; "None of these" is a real
              answer, and detection stays off (never blocking) until you say
              otherwise here or in Settings.
            </p>
            <select aria-label="Proxploy's own host" disabled={savingSelf || allHosts.isPending}
              defaultValue=""
              onChange={(e) => {
                const v = e.target.value
                saveSelfHost(v ? Number(v) : null)
              }}
              className="rounded-ctl border border-line bg-panel px-2 py-1.5 text-[12.5px] text-text">
              <option value="" disabled>Choose one…</option>
              {(allHosts.data ?? []).map(h => <option key={h.id} value={h.id}>{h.name}</option>)}
            </select>
            <div>
              <Button variant="ghost" disabled={savingSelf} onClick={() => saveSelfHost(null)}>
                None of these
              </Button>
            </div>
          </div>
        )}

        {step === S_DONE && (
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
    </div>
  )
}
