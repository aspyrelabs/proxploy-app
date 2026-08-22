import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

const BACKUPS = {
  backups: [
    { id: 11, host_id: 1, host_name: 'host-01', storage: 'pbs-ds',
      volid: 'pbs-ds:backup/ct/150/2026-07-30T02:00:00Z', guest_type: 'ct',
      guest_vmid: 150, guest_name: 'Immich', taken_at: '2026-07-30T02:00:00Z',
      size_bytes: 1073741824, verify_state: 'ok', notes: 'nightly' },
    { id: 12, host_id: 1, host_name: 'host-01', storage: 'pbs-ds',
      volid: 'pbs-ds:backup/vm/201/2026-07-30T03:00:00Z', guest_type: 'vm',
      guest_vmid: 201, guest_name: 'win11', taken_at: '2026-07-30T03:00:00Z',
      size_bytes: 5368709120, verify_state: 'failed', notes: null },
  ],
  stats: {
    total: 2, total_bytes: 6442450944, ok_count: 1, failed_count: 1,
    success_rate_30d: 50.0,
    datastores: [{ storage: 'pbs-ds', count: 2, size_bytes: 6442450944 }],
  },
  synced_at: '2026-07-31T09:00:00Z',
  stale: false,
}

const PRUNE = [
  { volid: 'pbs-ds:backup/ct/150/2026-07-30T02:00:00Z', type: 'ct', vmid: 150,
    ctime: 1753840800, mark: 'keep' },
  { volid: 'pbs-ds:backup/ct/150/2026-06-01T02:00:00Z', type: 'ct', vmid: 150,
    ctime: 1748743200, mark: 'remove' },
  { volid: 'pbs-ds:backup/vm/201/2026-05-01T02:00:00Z', type: 'vm', vmid: 201,
    ctime: 1746064800, mark: 'protected' },
]

const calls: { path: string; method: string; body: any }[] = []
let features: Record<string, boolean> = {
  'backups.pbs': true, 'backups.run': true, 'backups.restore': true,
  'backups.retention': true,
}
/** which 409 the next in-place restore should hit, if any */
let restoreGuard: 'confirm' | 'self' | null = null
/** GET /backups' own `stale` flag: location 2's ring only ever polls while
 *  this is true. */
let backupsStale = false
/** The one `backup.sync` job GET /jobs?status=running&kind=backup.sync
 *  reports back, or null for "nothing running". */
let syncJob: Record<string, unknown> | null = null
/** What Run now can see on host-01. Mutable so the "nothing to back up" case
 *  can empty them; the defaults are a normal node with one app and one VM. */
let apps: any[] = [{ id: 7, host_id: 1, name: 'Immich', ctid: 150 }]
let vms: any[] = [{ id: 9, host_id: 1, name: 'win11', vmid: 201 }]
let stores: any[] = [
  { host_id: 1, storage: 'local', type: 'dir', content: ['backup', 'iso'] },
  { host_id: 1, storage: 'local-lvm', type: 'lvmthin', content: ['rootdir', 'images'] },
]

/** Set to a pending promise to hold GET /apps; null lets it answer at once. */
let appsGate: Promise<unknown> | null = null

vi.mock('../api/client', () => {
  class ApiError extends Error {
    status: number; body: unknown
    constructor(status: number, body: unknown) {
      super(`API ${status}`); this.status = status; this.body = body
    }
  }
  return {
    ApiError,
    api: vi.fn((path: string, opts?: RequestInit) => {
      const method = (opts?.method ?? 'GET').toUpperCase()
      const body = opts?.body ? JSON.parse(String(opts.body)) : {}
      if (path === '/entitlements') {
        return Promise.resolve({ tier: 'builtin', features, grace: null, clock_skew: false })
      }
      if (method !== 'GET') calls.push({ path, method, body })
      if (path === '/backups') return Promise.resolve({ ...BACKUPS, stale: backupsStale })
      if (path === '/jobs?status=running&kind=backup.sync') {
        return Promise.resolve(syncJob ? [syncJob] : [])
      }
      if (path === '/schedules') return Promise.resolve([])
      if (path === '/hosts') return Promise.resolve([{ id: 1, name: 'host-01' }])
      // The Run now dialog's two honest preconditions: guests to dump, and a
      // storage that carries `backup` content. Not PBS: `local` below is a
      // plain directory store and vzdump writes there perfectly well.
      // appsGate holds /apps unresolved on demand, which is the only way to
      // stand still in the window RunDialog's placeholder covers: hosts
      // answered, so a host is chosen, while what is ON that host is not known
      // yet.
      if (path === '/apps') return (appsGate ?? Promise.resolve(null)).then(() => apps)
      if (path === '/vms') return Promise.resolve(vms)
      if (path === '/storage') return Promise.resolve(stores)
      if (path.startsWith('/backups/prune-preview')) return Promise.resolve(PRUNE)
      if (path === '/backups/run') {
        return Promise.resolve({ job: { id: 31, kind: 'backup.run', status: 'queued' } })
      }
      if (path.endsWith('/restore')) {
        if (body.mode === 'in_place' && restoreGuard === 'self') {
          // Unconditional refusal, `confirm` does not bypass it. Flat body,
          // matching main.py::problem_handler's `body.update(exc.detail)`
          // (Task 14 confirmed the real backend never nests under `detail`).
          return Promise.reject(new ApiError(409, {
            error: 'self_target', confirm_phrase: 'Immich',
            detail: 'Immich is the container Proxploy itself runs in. An in-place ' +
                    'restore would overwrite Proxploy mid-restore. Restore as new instead.',
          }))
        }
        if (body.mode === 'in_place' && restoreGuard === 'confirm' && !body.confirm) {
          return Promise.reject(new ApiError(409, {
            error: 'confirm_required', confirm_phrase: 'win11',
            detail: 'An in-place restore overwrites win11 with the contents of this backup.',
          }))
        }
        return Promise.resolve({ job: { id: 32, kind: 'backup.restore', status: 'queued' } })
      }
      if (method === 'DELETE') {
        return Promise.resolve({ job: { id: 33, kind: 'backup.delete', status: 'queued' } })
      }
      return Promise.resolve(null)
    }),
  }
})

vi.mock('@tanstack/react-router', async (orig) => ({
  ...(await orig() as object),
  Link: ({ children }: { children?: unknown }) => <a>{children as never}</a>,
  useNavigate: () => () => {},
  useSearch: () => ({}),
}))

import { BackupsPage } from '../routes/backups'

const wrap = () => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(<QueryClientProvider client={qc}><BackupsPage /></QueryClientProvider>)
}

describe('BackupsPage', () => {
  it('renders the datastore header, the three stat cards and the recent-backups table', async () => {
    calls.length = 0; restoreGuard = null
    wrap()
    expect(await screen.findByText(/Proxmox Backup Server · pbs-ds/)).toBeInTheDocument()
    expect(screen.getByText('Next scheduled')).toBeInTheDocument()
    expect(screen.getByText('Datastore used')).toBeInTheDocument()
    expect(screen.getByText('Success rate · 30d')).toBeInTheDocument()
    expect(screen.getByText('50%')).toBeInTheDocument()
    expect(screen.getByText('Immich')).toBeInTheDocument()
    expect(screen.getByText('win11')).toBeInTheDocument()
    expect(screen.getByText('5.0 GiB')).toBeInTheDocument()
  })

  it('opens a schedule dialog from "New job" instead of a disabled button', async () => {
    // The Phase 6 placeholder rendered a disabled button titled "…arrive with
    // the Phase 7 scheduler". Phase 7 owes it a working dialog.
    calls.length = 0
    wrap()
    const btn = await screen.findByRole('button', { name: /new job/i })
    expect(btn).not.toBeDisabled()
    fireEvent.click(btn)
    await waitFor(() => expect(screen.getByLabelText(/how often/i)).toBeInTheDocument())
    // "Backup" on its own reads as an unqualified backup of something
    // unspecified, and an operator reasonably asked whether these buttons were
    // about Proxploy's own data rather than their apps and VMs.
    expect(screen.getByText(/not Proxploy's own settings/)).toBeInTheDocument()
  })

  it('stands in for the header and for what is on the host, and clears both', async () => {
    calls.length = 0
    let open!: () => void
    appsGate = new Promise<void>((r) => { open = r })
    wrap()
    // First paint, before GET /backups has had a microtask to settle in.
    expect(screen.getByRole('status', { name: 'Loading backup datastore' })).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: 'Run now' }))
    // /hosts answers, so the single host is chosen, but /apps is still held:
    // this is the window where `blocked` is null and the guest sentence and
    // the storage field were simply absent.
    await waitFor(() =>
      expect(screen.getByRole('status', { name: 'Checking what is on this host' })).toBeTruthy())
    expect(screen.queryByLabelText(/archive lands on/i)).toBeNull()

    open()
    expect(await screen.findByText(/2 guests on host-01 will be backed up/)).toBeInTheDocument()
    expect(screen.getByLabelText(/archive lands on/i)).toBeInTheDocument()
    expect(screen.queryByRole('status', { name: 'Checking what is on this host' })).toBeNull()
    appsGate = null
  })

  it('runs a backup and swaps the dialog body for the job log', async () => {
    calls.length = 0
    wrap()
    fireEvent.click(await screen.findByRole('button', { name: 'Run now' }))
    // the single registered host is auto-selected once /hosts resolves; the
    // button is disabled until then, and a click on a disabled button is a no-op
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Start backup' })).toBeEnabled())
    fireEvent.click(screen.getByRole('button', { name: 'Start backup' }))
    await waitFor(() => expect(calls.length).toBe(1))
    expect(calls[0].path).toBe('/backups/run')
    // `storage` is sent, not left for PVE to pick: without it nothing on the
    // page or in the transcript could say where the archive went.
    expect(calls[0].body).toEqual({ guests: 'all', host_id: 1, storage: 'local' })
    expect(await screen.findByRole('button', { name: 'Close' })).toBeInTheDocument()
  })

  it('names the guests and the storage before the run, not after it', async () => {
    calls.length = 0
    wrap()
    fireEvent.click(await screen.findByRole('button', { name: 'Run now' }))
    // The scope was only ever in the source comments: one vzdump over every
    // guest on the chosen node. Saying so is what answers "what is it backing
    // up?" before the click instead of leaving it to be inferred from a
    // success line.
    expect(await screen.findByText(/2 guests on host-01 will be backed up/))
      .toBeInTheDocument()
    expect(screen.getByText(/Immich \(CT 150\), win11 \(VM 201\)/)).toBeInTheDocument()
    // Only the store that carries `backup` content is on offer.
    const target = screen.getByLabelText(/archive lands on/i)
    expect(within(target as HTMLElement).getByRole('option', { name: /local \(dir\)/ }))
      .toBeInTheDocument()
    expect(within(target as HTMLElement).queryByRole('option', { name: /local-lvm/ })).toBeNull()
  })

  it('refuses to run over a host with no containers or VMs, and says why', async () => {
    // The real bug: host 1 was node1, which has no guests at all. vzdump was
    // sent `all: 1`, dumped nothing, and PVE closed the task with exitstatus
    // OK, so the run reported plain success. Nothing about PBS: `local` is
    // still a perfectly good backup target below.
    calls.length = 0
    apps = []; vms = []
    wrap()
    fireEvent.click(await screen.findByRole('button', { name: 'Run now' }))
    expect(await screen.findByText(/no containers and no virtual machines/))
      .toBeInTheDocument()
    const start = screen.getByRole('button', { name: 'Start backup' })
    expect(start).toBeDisabled()
    // A disabled button with no stated reason is the other half of the same
    // problem, so the reason is on the control itself as well as on the page.
    expect(start).toHaveAttribute('title', expect.stringContaining('write nothing'))
    fireEvent.click(start)
    expect(calls.length).toBe(0)
    apps = [{ id: 7, host_id: 1, name: 'Immich', ctid: 150 }]
    vms = [{ id: 9, host_id: 1, name: 'win11', vmid: 201 }]
  })

  it('refuses to run when no storage on the host accepts backups', async () => {
    calls.length = 0
    stores = [{ host_id: 1, storage: 'local-lvm', type: 'lvmthin', content: ['rootdir'] }]
    wrap()
    fireEvent.click(await screen.findByRole('button', { name: 'Run now' }))
    expect(await screen.findByText(/No storage on host-01 accepts backups/))
      .toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Start backup' })).toBeDisabled()
    stores = [
      { host_id: 1, storage: 'local', type: 'dir', content: ['backup', 'iso'] },
      { host_id: 1, storage: 'local-lvm', type: 'lvmthin', content: ['rootdir', 'images'] },
    ]
  })

  it('asks for confirmation before deleting an archive, then fires the job', async () => {
    calls.length = 0
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false)
    wrap()
    await screen.findByText('Immich')
    fireEvent.click(screen.getAllByRole('button', { name: 'Delete' })[0])
    expect(confirmSpy).toHaveBeenCalled()
    expect(calls.length).toBe(0)          // declining deletes nothing
    confirmSpy.mockReturnValue(true)
    fireEvent.click(screen.getAllByRole('button', { name: 'Delete' })[0])
    await waitFor(() => expect(calls.length).toBe(1))
    expect(calls[0].method).toBe('DELETE')
    expect(calls[0].path).toBe('/backups/11')
    confirmSpy.mockRestore()
  })

  it('takes a typed confirmation for an in-place restore over another guest', async () => {
    calls.length = 0; restoreGuard = 'confirm'
    wrap()
    await screen.findByText('win11')
    fireEvent.click(screen.getAllByRole('button', { name: 'Restore' })[1])
    fireEvent.click(await screen.findByLabelText(/In place/i))
    fireEvent.click(screen.getByRole('button', { name: 'Start restore' }))
    await waitFor(() => expect(calls.length).toBe(1))
    expect(calls[0].body).toEqual({ mode: 'in_place' })

    expect(await screen.findByText(/An in-place restore overwrites win11/)).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText(/type/i), { target: { value: 'win11' } })
    fireEvent.click(screen.getByRole('button', { name: /^Confirm$/ }))
    await waitFor(() => expect(calls.length).toBe(2))
    expect(calls[1].body).toEqual({ mode: 'in_place', confirm: 'win11' })
    restoreGuard = null
  })

  it('refuses an in-place restore over Proxploy itself instead of offering a confirm box', async () => {
    calls.length = 0; restoreGuard = 'self'
    wrap()
    await screen.findByText('Immich')
    fireEvent.click(screen.getAllByRole('button', { name: 'Restore' })[0])
    fireEvent.click(await screen.findByLabelText(/In place/i))
    fireEvent.click(screen.getByRole('button', { name: 'Start restore' }))
    await waitFor(() => expect(calls.length).toBe(1))
    // the backend's own sentence, and NO typed-confirmation control: re-POSTing
    // with the phrase gets the same 409, so offering one would be a lie
    expect(await screen.findByText(/Restore as new instead/)).toBeInTheDocument()
    expect(screen.queryByLabelText(/type/i)).toBeNull()
    expect(screen.queryByRole('button', { name: /^Confirm$/ })).toBeNull()
    expect(calls.length).toBe(1)
    restoreGuard = null
  })

  it('disables Delete without backups.retention, the entitlement DELETE /backups/{id} now checks', async () => {
    // BLOCKING 3/item 6 moved the route's gate from backups.pbs to
    // backups.retention; the button must follow, or a tenant with backups.pbs
    // and without backups.retention gets a Delete button that just 403s.
    calls.length = 0
    features = { 'backups.pbs': true, 'backups.run': true, 'backups.restore': true }
    wrap()
    const btn = (await screen.findAllByRole('button', { name: 'Delete' }))[0]
    expect(btn).toBeDisabled()
    expect(btn.getAttribute('title')).toMatch(/not included in your plan/i)
  })

  it('veils the retention preview without backups.retention, and marks volumes when entitled', async () => {
    calls.length = 0
    features = { 'backups.pbs': true, 'backups.run': true, 'backups.restore': true }
    const veiled = wrap()
    expect(await screen.findByText(/Retention preview is a Pro feature/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Unlock Pro/i })).toBeInTheDocument()
    veiled.unmount()

    features = { 'backups.pbs': true, 'backups.run': true, 'backups.restore': true,
                 'backups.retention': true }
    wrap()
    // enabled only once /backups resolves, the datastore and its host come from it
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Preview retention' })).toBeEnabled())
    fireEvent.click(screen.getByRole('button', { name: 'Preview retention' }))
    expect(await screen.findByText('remove')).toBeInTheDocument()
    expect(screen.getByText('protected')).toBeInTheDocument()
    expect(screen.getAllByText('keep').length).toBeGreaterThan(0)
    expect(screen.getByText(/deletes nothing/i)).toBeInTheDocument()
  })

  it('offers PBS datastore connect, reusing StorageForm pre-set to type pbs', async () => {
    // doc 10 lists "PBS datastore connect" as a Phase 6 Backups deliverable.
    // Connecting PBS *is* attaching a storage of type pbs, so this asserts the
    // affordance exists and opens Task 13's form in the right mode, not that
    // a second, parallel PBS form was built.
    wrap()
    fireEvent.click(await screen.findByRole('button', { name: 'Connect PBS' }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByLabelText(/Type/i)).toHaveValue('pbs')
  })

  // services/backupjobs.py::sync_backups is the only genuinely granular
  // progress in the product (int((i+1)/len(host_ids)*100) per host), and the
  // only place that job is displayed at all is the "refreshing from
  // Proxmox…" banner GET /backups' own `stale` flag already renders.
  describe('the backup-sync banner', () => {
    it('shows the plain banner with no ring while nothing has reported progress', async () => {
      backupsStale = true
      syncJob = null
      wrap()
      expect(await screen.findByText(/refreshing from proxmox/i)).toBeInTheDocument()
      expect(screen.queryByRole('status')).toBeNull()
    })

    // Seeded straight from the first poll: a sync already partway through
    // when the page mounts must never flash 0 before showing 66.
    it('shows the ring at the running sync job\'s real progress, never a zero', async () => {
      backupsStale = true
      syncJob = {
        id: 40, kind: 'backup.sync', status: 'running',
        target_type: 'system', target_id: null, params: null, result: null,
        error: null, progress_pct: 66, requested_by: null, schedule_id: null,
        started_at: '2026-08-12T09:00:00Z', finished_at: null,
        created_at: '2026-08-12T09:00:00Z',
      }
      wrap()
      await waitFor(() => expect(screen.getByRole('status')).toHaveAttribute(
        'aria-label', expect.stringContaining('66 percent')))
      expect(screen.queryByText('0')).toBeNull()
    })

    it('polls for the running sync job only while the cache is stale', async () => {
      backupsStale = false
      syncJob = null
      const { api } = await import('../api/client')
      vi.mocked(api).mockClear()
      wrap()
      await screen.findByText(/Proxmox Backup Server/)
      expect(vi.mocked(api).mock.calls.some(
        (c) => c[0] === '/jobs?status=running&kind=backup.sync')).toBe(false)
    })
  })
})
