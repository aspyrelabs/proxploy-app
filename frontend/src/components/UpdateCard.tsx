import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api, apiErrorDetail } from '../api/client'
import { useApplyUpdate, useUpdateStatus } from '../api/account'
import { notify } from '../lib/notify'
import { Button, amberLinkCls } from './ui/button'
import { Progress, ProgressLabel } from './ui/progress'
import { Skeleton, SkeletonGroup, SkeletonLine } from './ui/skeleton'

// Matches backend/proxploy/config.py's update_timeout_s default. The updater
// restarts the very server that would otherwise report success, so the
// client can only ever detect success (the version actually changed) or give
// up and say so honestly -- it must never claim success on a timeout.
const UPDATE_TIMEOUT_MS = 600_000
const POLL_INTERVAL_MS = 3000

type PollState = 'idle' | 'polling' | 'success' | 'timeout'

export function UpdateCard() {
  const status = useUpdateStatus()
  const apply = useApplyUpdate()
  const [poll, setPoll] = useState<PollState>('idle')
  const [newVersion, setNewVersion] = useState<string | null>(null)
  const baseline = useRef<string | null>(null)

  const versionPoll = useQuery({
    queryKey: ['meta', 'version-poll'],
    queryFn: () => api<{ version: string }>('/meta/version'),
    enabled: poll === 'polling',
    refetchInterval: POLL_INTERVAL_MS,
  })

  // Success: the polled version actually moved off the version we recorded
  // before applying. Only a real change counts -- never a guess.
  useEffect(() => {
    if (poll === 'polling' && versionPoll.data && versionPoll.data.version !== baseline.current) {
      setNewVersion(versionPoll.data.version)
      setPoll('success')
    }
  }, [poll, versionPoll.data])

  // Timeout: the server may be mid-restart and simply not answering yet.
  // One timer per polling attempt, cleared the moment polling stops for any
  // other reason (success, or a fresh update started).
  useEffect(() => {
    if (poll !== 'polling') return
    const t = setTimeout(() => setPoll((p) => (p === 'polling' ? 'timeout' : p)), UPDATE_TIMEOUT_MS)
    return () => clearTimeout(t)
  }, [poll])

  const startUpdate = () => {
    const latest = status.data?.latest
    if (!latest) return
    baseline.current = status.data?.current ?? null
    setNewVersion(null)
    apply.mutate(latest, {
      onSuccess: () => setPoll('polling'),
      onError: (e) => notify.error(apiErrorDetail(e, 'Could not start the update, try again.')),
    })
  }

  if (status.data == null) {
    return (
      <section className="rounded-card border border-line-soft bg-panel p-5">
        <h2 className="font-display text-[15px] font-semibold">Updates</h2>
        {status.isError ? (
          <p className="mt-2 text-[12.5px] text-text-3">Could not load update status.</p>
        ) : (
          // The word "Loading…" was doing a skeleton's job badly: it is a
          // 12.5px line where a 13px line is about to be, so the card shifted
          // by a pixel and by a whole button's height the moment the status
          // arrived. These are the two things that always land, the current
          // version and either "You're up to date." or the update button, so
          // the card is already its final size before the answer comes back.
          <SkeletonGroup label="Loading update status">
            <SkeletonLine className="mt-2 w-48 text-[13px]" />
            <Skeleton className="mt-3 h-[35px] w-40 rounded-ctl" />
          </SkeletonGroup>
        )}
      </section>
    )
  }

  const s = status.data
  const currentVersion = poll === 'success' && newVersion ? newVersion : s.current

  return (
    <section className="rounded-card border border-line-soft bg-panel p-5">
      <h2 className="font-display text-[15px] font-semibold">Updates</h2>
      <p className="mt-2 text-[13px] text-text-2">Current version: {currentVersion}</p>

      {s.error && (
        <p className="mt-2 rounded-ctl border border-amber/40 bg-amber-dim p-2 text-[12.5px] text-amber">
          {s.error}
        </p>
      )}

      {!s.error && !s.update_available && poll !== 'success' && (
        <p className="mt-2 text-[12.5px] text-text-3">You're up to date.</p>
      )}

      {!s.error && s.update_available && poll !== 'success' && (
        s.can_self_apply ? (
          <div className="mt-3">
            <Button disabled={apply.isPending || poll === 'polling'} onClick={startUpdate}>
              {poll === 'polling' ? 'Updating…' : `Update to ${s.latest}`}
            </Button>
            {s.notes_url && (
              <a href={s.notes_url} target="_blank" rel="noopener noreferrer"
                className={`ml-3 text-[12px] ${amberLinkCls}`}>
                Release notes
              </a>
            )}
            {poll === 'polling' && (
              // Indeterminate on purpose: this waits for the server to come
              // back on a new version, and there is no percentage anywhere in
              // that. The bar says "busy" honestly, which is the whole reason
              // ui/progress.tsx has a null mode.
              <Progress className="mt-3 max-w-sm">
                <ProgressLabel>Updating Proxploy, it will restart itself</ProgressLabel>
              </Progress>
            )}
            {poll === 'timeout' && (
              <p className="mt-2 text-[12.5px] text-red">
                Lost contact with the server while updating, check the host.
              </p>
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
              <Button variant="ghost" className="px-2 py-1 text-[11px]"
                onClick={() => { void navigator.clipboard?.writeText(s.compose_hint ?? '') }}>
                Copy
              </Button>
            </div>
          </div>
        )
      )}

      {poll === 'success' && (
        <p className="mt-2 text-[12.5px] text-green">Updated, now running {newVersion}.</p>
      )}
    </section>
  )
}
