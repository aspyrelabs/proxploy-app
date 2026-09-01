import { useEffect, useState } from 'react'
import { type UpdateLog, useApplyUpdate, useUpdateLog, useUpdateStatus } from '../api/account'
import { apiErrorDetail } from '../api/client'
import { notify } from '../lib/notify'
import { Button, amberLinkCls } from './ui/button'
import { Icon } from './ui/icon'
import { Skeleton, SkeletonGroup, SkeletonLine } from './ui/skeleton'
import { TerminalPanel } from './TerminalPanel'

const CHANGELOG_URL = 'https://proxploy.com/changelog.txt'
const DEV_CHANNEL_URL = 'https://web.proxploy.dev/releases/latest'
const PROD_CHANNEL_URL = 'https://proxploy.com/releases/latest'
const PROD_CHANNEL_FLOOR = [1, 2, 0]

function versionParts(v: string): number[] {
  return v.split('.').map((p) => parseInt(p, 10) || 0)
}

function versionAtLeast(v: string, floor: number[]): boolean {
  const parts = versionParts(v)
  for (let i = 0; i < floor.length; i++) {
    const a = parts[i] ?? 0, b = floor[i]
    if (a !== b) return a > b
  }
  return true
}

function manualUpdateCommand(current: string, latest: string): string {
  const channel = versionAtLeast(current, PROD_CHANNEL_FLOOR) ? PROD_CHANNEL_URL : DEV_CHANNEL_URL
  return `/opt/proxploy/bin/proxploy-update --to ${latest} --channel ${channel}`
}

function ManualUpdateSteps({ current, latest }: { current: string; latest: string }) {
  const [open, setOpen] = useState(false)
  const command = manualUpdateCommand(current, latest)

  return (
    <div className="mt-3">
      <button type="button" aria-expanded={open} onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-1.5 text-left text-[12.5px] text-text-2
                   transition hover:text-text">
        <Icon name="expand_more" size={16}
          className={`shrink-0 text-text-3 transition-transform motion-reduce:transition-none
                      ${open ? 'rotate-180 text-amber' : ''}`} />
        Prefer to update it yourself?
      </button>
      {open && (
        <div className="mt-2 max-w-lg">
          <p className="text-[11.5px] text-text-3">
            Run this as root on the box. For an LXC install, run pct enter &lt;ctid&gt;
            from the Proxmox host first to get a root shell in the container.
          </p>
          <div className="mt-2 flex items-center gap-2">
            <code className="min-w-0 flex-1 overflow-x-auto rounded-ctl border border-line
                             bg-[#0a0e14] px-2 py-1.5 font-mono text-[11px] text-text-2">
              {command}
            </code>
            <Button size="sm" variant="ghost"
              onClick={() => { void navigator.clipboard?.writeText(command) }}>
              Copy
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}

function outcomeText(l: UpdateLog): string {
  if (l.state === 'succeeded') return `Updated, now running ${l.version}.`
  if (l.state === 'failed') return `Update to ${l.version} failed${l.reason ? `: ${l.reason}` : '.'}`
  if (l.state === 'rolled_back') {
    return `Update to ${l.version} failed and was put back on ${l.from}${l.reason ? `: ${l.reason}` : '.'}`
  }
  return ''
}

function toLines(l: UpdateLog | undefined) {
  return (l?.lines ?? []).map((message) => ({ stream: 'stdout', message }))
}

export function UpdateCard() {
  const status = useUpdateStatus()
  const apply = useApplyUpdate()
  const [applyingVersion, setApplyingVersion] = useState<string | null>(null)
  const log = useUpdateLog(applyingVersion != null)
  const l = log.data

  useEffect(() => {
    if (applyingVersion && l && l.version === applyingVersion) setApplyingVersion(null)
  }, [applyingVersion, l])

  const isRunning = applyingVersion != null || l?.state === 'running'
  const isSucceeded = applyingVersion == null && l?.state === 'succeeded'
  const isTerminalFail = applyingVersion == null && (l?.state === 'failed' || l?.state === 'rolled_back')

  const startUpdate = () => {
    const latest = status.data?.latest
    if (!latest) return
    setApplyingVersion(latest)
    apply.mutate(latest, {
      onSuccess: () => { void log.refetch() },
      onError: (e) => {
        setApplyingVersion(null)
        notify.error(apiErrorDetail(e, 'Could not start the update, try again.'))
      },
    })
  }

  if (status.data == null) {
    return (
      <section className="rounded-card border border-line-soft bg-panel p-5">
        <h2 className="font-display text-[15px] font-semibold">Updates</h2>
        {status.isError ? (
          <p className="mt-2 text-[12.5px] text-text-3">Could not load update status.</p>
        ) : (
          <SkeletonGroup label="Loading update status">
            <SkeletonLine className="mt-2 w-48 text-[13px]" />
            <Skeleton className="mt-3 h-[35px] w-40 rounded-ctl" />
          </SkeletonGroup>
        )}
      </section>
    )
  }

  const s = status.data
  const currentVersion = isSucceeded && l?.version ? l.version : s.current

  return (
    <section className="rounded-card border border-line-soft bg-panel p-5">
      <h2 className="font-display text-[15px] font-semibold">Updates</h2>
      <p className="mt-2 text-[13px] text-text-2">Current version: {currentVersion}</p>

      {s.error && (
        <p className="mt-2 rounded-ctl border border-amber/40 bg-amber-dim p-2 text-[12.5px] text-amber">
          {s.error}
        </p>
      )}

      {!s.error && !s.update_available && !isSucceeded && (
        <p className="mt-2 text-[12.5px] text-text-3">You're up to date.</p>
      )}

      {!s.error && s.update_available && !isSucceeded && (
        s.can_self_apply ? (
          <div className="mt-3">
            <Button disabled={apply.isPending || isRunning} onClick={startUpdate}>
              {isRunning ? 'Updating…' : `Update to ${s.latest}`}
            </Button>
            <a href={s.notes_url ?? CHANGELOG_URL} target="_blank" rel="noopener noreferrer"
              className={`ml-3 text-[12px] ${amberLinkCls}`}>
              Release notes
            </a>
            {s.latest && <ManualUpdateSteps current={s.current} latest={s.latest} />}
            {isRunning && (
              <div className="mt-3 max-w-lg">
                <p className="mb-1 text-[12.5px] text-text-3">
                  Updating Proxploy, it will restart itself.
                </p>
                <TerminalPanel lines={toLines(l)} height={200} />
              </div>
            )}
            {isTerminalFail && l && (
              <div className="mt-3 max-w-lg">
                <p className="text-[12.5px] text-red">{outcomeText(l)}</p>
                <TerminalPanel lines={toLines(l)} height={200} />
              </div>
            )}
          </div>
        ) : (
          <div className="mt-3">
            <p className="text-[12.5px] text-text-3">
              Proxploy does not update its own container, run this on the Docker host.
            </p>
            <div className="mt-2 flex items-center gap-2">
              <code className="min-w-0 flex-1 rounded-ctl border border-line bg-panel-2
                               px-2 py-1.5 font-mono text-[12px] text-text">
                {s.compose_hint}
              </code>
              <Button size="sm" variant="ghost"
                onClick={() => { void navigator.clipboard?.writeText(s.compose_hint ?? '') }}>
                Copy
              </Button>
            </div>
          </div>
        )
      )}

      {isSucceeded && l && (
        <div className="mt-2 max-w-lg">
          <p className="text-[12.5px] text-green">{outcomeText(l)}</p>
          <TerminalPanel lines={toLines(l)} height={200} />
        </div>
      )}
    </section>
  )
}
