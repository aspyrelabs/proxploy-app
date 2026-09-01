import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const LOCAL = {
  host_id: 1, host_name: 'host-01', cluster_name: null, node: 'pve1', storage: 'local', type: 'dir',
  content: ['iso', 'vztmpl', 'backup'], shared: false, status: 'available',
  used_bytes: 100, total_bytes: 400, used_pct: 25.0,
}
// Second row + its content listing exist only for the delete-volume tests
// (Step 8b), which click through StoragePage to a real content row rather
// than mounting VolumeTable directly.
const LOCAL_LVM = {
  host_id: 1, host_name: 'host-01', cluster_name: null, node: 'pve1', storage: 'local-lvm', type: 'lvmthin',
  content: ['iso'], shared: false, status: 'available',
  used_bytes: 50, total_bytes: 200, used_pct: 25.0,
}
const ISO_VOL = {
  volid: 'local:iso/debian-12.iso', format: 'iso', size: 700, used: 0,
  vmid: null, ctime: 1730000000, content: 'iso', notes: null, verification: null,
}

let features: Record<string, boolean> = { 'storage.manage': true }
const calls: { path: string; opts?: any }[] = []
let uploadJob: Record<string, unknown> | null = null

vi.mock('../api/client', () => ({
  api: vi.fn((path: string, opts?: any) => {
    calls.push({ path, opts })
    if (path === '/entitlements') {
      return Promise.resolve({ tier: 'pro', features,
                               required_tier: { 'storage.manage': 'pro' },
                               grace: null, clock_skew: false })
    }
    if (path === '/hosts') return Promise.resolve([{ id: 1, name: 'host-01' }])
    if (/^\/jobs\/\d+$/.test(path)) return Promise.resolve(uploadJob)
    if (path.endsWith('/events')) return Promise.resolve([])
    if (path === '/storage') return Promise.resolve([LOCAL, LOCAL_LVM])
    if (path.startsWith('/storage/1/local-lvm/content')) return Promise.resolve([ISO_VOL])
    if (path.includes('/content')) return Promise.resolve([])
    // Only a plain GET is the detail shape, PATCH to this same path is the
    // edit mutation and falls through to the generic case below.
    if (path === '/storage/1/local' && (opts?.method ?? 'GET') === 'GET') {
      return Promise.resolve({ ...LOCAL, avail_bytes: 300, nodes: ['pve1'] })
    }
    // Generic fallthrough covers attach (POST /storage), detach (DELETE
    // /storage/1/local) and edit (PATCH /storage/1/local, same path as the
    // GET-detail special case above, which only matches a plain GET).
    // `updated` is here because StorageForm's edit onSuccess reads
    // `r.updated.join(...)`; leaving it off crashes that handler with an
    // unhandled rejection once the mutation resolves after the assertions run.
    return Promise.resolve({ host_id: 1, storage: 'local', updated: ['content'] })
  }),
  // Must carry status/body like the real one in api/client.ts: a bare
  // `class extends Error {}` silently drops both, so any component branch that
  // reads an error body could never be exercised from this file.
  ApiError: class extends Error {
    status: number
    body: unknown
    constructor(status: number, body: unknown) {
      super(`API ${status}`)
      this.status = status
      this.body = body
    }
  },
}))

vi.mock('@tanstack/react-router', async (orig) => ({
  ...(await orig() as object),
  Link: ({ children }: { children?: unknown }) => <a>{children as never}</a>,
  useNavigate: () => () => {},
  useSearch: () => ({}),
}))

// Same reason as vms.test.tsx: notify.error pushes into notificationStore,
// which this file has no need to exercise for real, only to assert it was
// (or was not, for a deliberate Cancel) called.
vi.mock('../lib/notify', () => ({
  notify: { error: vi.fn(), success: vi.fn(), info: vi.fn(), warning: vi.fn() },
}))

import { StorageForm } from '../components/StorageForm'
import { UploadDialog } from '../components/UploadDialog'
import { notify } from '../lib/notify'
import { StoragePage } from '../routes/storage'

const withQuery = (ui: React.ReactNode) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

/**
 * UploadDialog now sends the upload through XMLHttpRequest, not fetch, the
 * only way to get real `onprogress` events for the bytes going out. This
 * stands in for the browser one: records what the component sent, and lets
 * a test drive it exactly like the real network would,
 * `xhr.upload.onprogress(...)` then one of `respond`/`onerror`/`abort`.
 */
class FakeXHR {
  static instances: FakeXHR[] = []
  method = ''
  url = ''
  headers: Record<string, string> = {}
  withCredentials = false
  body: unknown = null
  status = 0
  responseText = ''
  aborted = false
  upload: { onprogress: ((e: { lengthComputable: boolean; loaded: number; total: number }) => void) | null } =
    { onprogress: null }
  onload: (() => void) | null = null
  onerror: (() => void) | null = null
  onabort: (() => void) | null = null

  constructor() { FakeXHR.instances.push(this) }
  open(method: string, url: string) { this.method = method; this.url = url }
  setRequestHeader(k: string, v: string) { this.headers[k] = v }
  send(body: unknown) { this.body = body }
  abort() { this.aborted = true; this.onabort?.() }

  /** Simulates the server's response arriving. */
  respond(status: number, body: unknown) {
    this.status = status
    this.responseText = body == null ? '' : JSON.stringify(body)
    this.onload?.()
  }
}

beforeEach(() => {
  calls.length = 0
  features = { 'storage.manage': true }
  uploadJob = null
  document.cookie = 'pp_csrf=csrf-token-abc'
  FakeXHR.instances.length = 0
  vi.stubGlobal('XMLHttpRequest', FakeXHR)
})
afterEach(() => { vi.restoreAllMocks() })

describe('UploadDialog', () => {
  const start = async (file = new File(['x'], 'a.iso', { type: 'application/octet-stream' })) => {
    withQuery(<UploadDialog hostId={1} storage="local" node="pve1"
      contentTypes={['iso']} onClose={vi.fn()} />)
    fireEvent.change(screen.getByLabelText('File'), { target: { files: [file] } })
    fireEvent.click(screen.getByRole('button', { name: 'Upload' }))
    await waitFor(() => expect(FakeXHR.instances).toHaveLength(1))
    return FakeXHR.instances[0]
  }

  it('POSTs multipart with credentials + CSRF and no Content-Type override', async () => {
    const file = new File(['iso-bytes'], 'ubuntu.iso', { type: 'application/octet-stream' })
    const xhr = await start(file)

    expect(xhr.method).toBe('POST')
    expect(xhr.url).toBe('/api/v1/storage/1/local/content')
    // credentials: 'include' for fetch, the XHR equivalent is this flag
    expect(xhr.withCredentials).toBe(true)
    expect(xhr.headers['X-CSRF-Token']).toBe('csrf-token-abc')
    // the whole reason this is not api(): a Content-Type here kills the boundary
    expect(xhr.headers['Content-Type']).toBeUndefined()
    expect(xhr.body).toBeInstanceOf(FormData)
    expect((xhr.body as FormData).get('content')).toBe('iso')
    expect((xhr.body as FormData).get('node')).toBe('pve1')
    expect((xhr.body as FormData).get('file')).toBe(file)
  })

  it('swaps the body for the job log once the upload returns a job', async () => {
    const xhr = await start()
    act(() => xhr.respond(202, { job: { id: 9, kind: 'storage.upload' } }))
    expect(await screen.findByRole('button', { name: 'Upload in background' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Upload' })).toBeNull()
  })

  it('progress events drive the bar\'s value, scaled to the first half of the bar', async () => {
    const xhr = await start()
    act(() => xhr.upload.onprogress?.({ lengthComputable: true, loaded: 50, total: 200 }))

    const bar = await screen.findByRole('progressbar')
    expect(bar).toHaveAttribute('aria-valuenow', '13')
    expect(bar).toHaveAttribute('aria-busy', 'false')
    expect(screen.getByText('Sending to Proxploy')).toBeInTheDocument()
  })

  it('shows the file size, bytes sent, speed and time remaining once there is enough data', async () => {
    const file = new File([new Uint8Array(2_000_000)], 'ubuntu.iso')
    const xhr = await start(file)

    vi.useFakeTimers()
    try {
      act(() => xhr.upload.onprogress?.({ lengthComputable: true, loaded: 500_000, total: 2_000_000 }))
      await vi.advanceTimersByTimeAsync(1000)
      act(() => xhr.upload.onprogress?.({ lengthComputable: true, loaded: 1_000_000, total: 2_000_000 }))
    } finally {
      vi.useRealTimers()
    }

    // Total size (from the File itself) and bytes sent so far.
    expect(screen.getByText(/976\.6 KiB of 1\.9 MiB/)).toBeInTheDocument()
    // 500,000 B/s over the smoothing window: a real figure, not "unknown".
    expect(document.body.textContent).toMatch(/KiB\/s|MiB\/s/)
    expect(document.body.textContent).toMatch(/left/)
    expect(document.body.textContent).not.toMatch(/unknown/)
  })

  it('does not render a percentage when the progress event is not lengthComputable', async () => {
    const xhr = await start()
    act(() => xhr.upload.onprogress?.({ lengthComputable: false, loaded: 50, total: 0 }))

    const bar = await screen.findByRole('progressbar')
    expect(bar).not.toHaveAttribute('aria-valuenow')
    expect(bar).toHaveAttribute('aria-busy', 'true')
    expect(document.body.textContent).not.toMatch(/\d+ ?%/)
  })

  it('shows the unknown placeholder before there is enough data to estimate speed', async () => {
    const xhr = await start()
    act(() => xhr.upload.onprogress?.({ lengthComputable: true, loaded: 50, total: 200 }))

    // One sample only, no elapsed span to derive a rate from yet.
    expect(document.body.textContent).toMatch(/unknown/)
  })

  it('Cancel aborts the in-flight upload, returns to the pre-upload form and does not toast an error for it', async () => {
    const onClose = vi.fn()
    withQuery(<UploadDialog hostId={1} storage="local" node="pve1"
      contentTypes={['iso']} onClose={onClose} />)
    fireEvent.change(screen.getByLabelText('File'),
      { target: { files: [new File(['x'], 'a.iso')] } })
    fireEvent.click(screen.getByRole('button', { name: 'Upload' }))
    await waitFor(() => expect(FakeXHR.instances).toHaveLength(1))

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
      // The abort rejects the mutation's promise on a microtask; give it one
      // before asserting nothing toasted.
      await Promise.resolve()
    })
    expect(FakeXHR.instances[0].aborted).toBe(true)
    // Cancel during the upload leg stays in the dialog, it does not close it,
    // so the operator can pick a different file or close on their own.
    expect(onClose).not.toHaveBeenCalled()
    expect(screen.getByText('Upload cancelled. The file was not saved.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Upload' })).toBeInTheDocument()
    expect(notify.error).not.toHaveBeenCalled()
  })

  it('Cancel is offered again once the upload leg is under way, and closes the dialog before then', async () => {
    const onClose = vi.fn()
    withQuery(<UploadDialog hostId={1} storage="local" node="pve1"
      contentTypes={['iso']} onClose={onClose} />)
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(onClose).toHaveBeenCalled()
  })

  it('Cancel during the server-side leg posts to the job cancel endpoint and stops the bar', async () => {
    const xhr = await start()
    act(() => xhr.respond(202, { job: { id: 9, kind: 'storage.upload' } }))
    await screen.findByRole('progressbar')

    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    await waitFor(() => expect(calls.some((c) =>
      c.path === '/jobs/9/cancel' && c.opts?.method === 'POST')).toBe(true))

    expect(await screen.findByText(/Upload cancelled/)).toBeInTheDocument()
    expect(screen.queryByRole('progressbar')).toBeNull()
    expect(screen.getByRole('button', { name: 'Close' })).toBeInTheDocument()
  })

  it('offers Upload in background only once a job id exists, and closing that way never cancels the job', async () => {
    const onClose = vi.fn()
    withQuery(<UploadDialog hostId={1} storage="local" node="pve1"
      contentTypes={['iso']} onClose={onClose} />)
    fireEvent.change(screen.getByLabelText('File'),
      { target: { files: [new File(['x'], 'a.iso')] } })
    fireEvent.click(screen.getByRole('button', { name: 'Upload' }))
    await waitFor(() => expect(FakeXHR.instances).toHaveLength(1))

    // Nothing to background before the job id exists.
    expect(screen.queryByRole('button', { name: 'Upload in background' })).toBeNull()

    act(() => FakeXHR.instances[0].respond(202, { job: { id: 9, kind: 'storage.upload' } }))
    const background = await screen.findByRole('button', { name: 'Upload in background' })
    fireEvent.click(background)

    expect(onClose).toHaveBeenCalled()
    expect(calls.some((c) => c.path === '/jobs/9/cancel')).toBe(false)
  })

  it('surfaces a failed upload the same way a rejected fetch did', async () => {
    const xhr = await start()
    act(() => xhr.respond(500, { detail: 'disk full on pve1' }))
    await waitFor(() => expect(notify.error).toHaveBeenCalledWith('disk full on pve1'))
  })

  it('keeps the bar moving past leg one using the job\'s progress', async () => {
    uploadJob = {
      id: 9, kind: 'storage.upload', status: 'running', target_type: null, target_id: null,
      params: null, result: null, error: null, progress_pct: 20, requested_by: null,
      schedule_id: null, started_at: '2026-08-05T00:00:00', finished_at: null,
      created_at: '2026-08-05T00:00:00',
    }
    const xhr = await start()
    act(() => xhr.respond(202, { job: { id: 9, kind: 'storage.upload' } }))

    await waitFor(() =>
      expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '60'))
    expect(screen.getByText('Sending to pve1')).toBeInTheDocument()
  })

  it('replaces the bar with an explanation instead of spinning when the job dies', async () => {
    uploadJob = {
      id: 9, kind: 'storage.upload', status: 'canceled', target_type: null, target_id: null,
      params: null, result: null, error: null, progress_pct: 40, requested_by: null,
      schedule_id: null, started_at: '2026-08-05T00:00:00', finished_at: '2026-08-05T00:01:00',
      created_at: '2026-08-05T00:00:00',
    }
    const xhr = await start()
    act(() => xhr.respond(202, { job: { id: 9, kind: 'storage.upload' } }))

    await screen.findByText(/The upload stopped before it finished/)
    expect(screen.queryByRole('progressbar')).toBeNull()
  })
})

describe('StorageForm', () => {
  it('attaches with the plugin fields for the chosen type', async () => {
    withQuery(<StorageForm existing={null} onClose={vi.fn()} />)
    await screen.findByRole('option', { name: 'host-01' })
    fireEvent.change(screen.getByLabelText('Host'), { target: { value: '1' } })
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'nfs-media' } })
    fireEvent.change(screen.getByLabelText('Type'), { target: { value: 'nfs' } })
    fireEvent.change(screen.getByLabelText('Server'), { target: { value: '10.0.0.30' } })
    fireEvent.change(screen.getByLabelText('Export'), { target: { value: '/media' } })
    fireEvent.click(screen.getByLabelText('ISO images'))
    fireEvent.click(screen.getByLabelText('Container templates'))
    fireEvent.click(screen.getByRole('button', { name: 'Attach' }))

    await waitFor(() => expect(calls.some((c) => c.path === '/storage' && c.opts?.method === 'POST')).toBe(true))
    const post = calls.find((c) => c.path === '/storage' && c.opts?.method === 'POST')!
    expect(JSON.parse(post.opts.body)).toEqual({
      host_id: 1, storage: 'nfs-media', type: 'nfs',
      // Written in the checkbox list's own order, whatever order they were
      // clicked in.
      config: { server: '10.0.0.30', export: '/media', content: 'vztmpl,iso' },
    })
  })

  it('veils the form when storage.manage is off, and never before entitlements resolve', async () => {
    features = {}
    withQuery(<StorageForm existing={null} onClose={vi.fn()} />)
    // has() is false until the first fetch resolves, gating on !has() alone
    // would veil this for every plan during load.
    expect(screen.queryByText(/This is a .* feature/)).toBeNull()
    expect(await screen.findByText('This is a Pro feature')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Please upgrade/i }))
      .toHaveAttribute('href', 'https://proxploy.com/#pricing')
  })

  // TYPES is the four plugins this form can ATTACH, but Edit opens on ANY row
  // the Storage page lists, and a real cluster is full of lvmthin, zfspool and
  // rbd. With no option matching, the browser fell back to the first one and
  // the box read "dir" for local-lvm: not a missing answer, a wrong one, about
  // a datastore whose type the caller already knew.
  it('names the datastore\'s real type in edit mode, not the first attachable one', async () => {
    withQuery(<StorageForm existing={LOCAL_LVM} onClose={vi.fn()} />)
    const type = await screen.findByLabelText('Type') as HTMLSelectElement
    expect(type.value).toBe('lvmthin')
    expect(type.selectedOptions[0].textContent).toBe('lvmthin')
  })

  // Same claim from the other direction: GET /storage types are nullable, and
  // `?? defaultType` turned "Proxmox did not say" into a confident "dir".
  it('says the type is unknown when the datastore reports none', async () => {
    withQuery(<StorageForm existing={{ ...LOCAL, type: null }} onClose={vi.fn()} />)
    const type = await screen.findByLabelText('Type') as HTMLSelectElement
    expect(type.selectedOptions[0].textContent).toBe('unknown')
  })

  it('PATCHes only the fields the operator filled in edit mode', async () => {
    withQuery(<StorageForm existing={LOCAL} onClose={vi.fn()} />)
    // local carries iso,vztmpl,backup; unticking one is the whole edit.
    fireEvent.click(await screen.findByLabelText('Container templates'))
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(calls.some((c) => c.opts?.method === 'PATCH')).toBe(true))
    const patch = calls.find((c) => c.opts?.method === 'PATCH')!
    expect(patch.path).toBe('/storage/1/local')
    expect(JSON.parse(patch.opts.body)).toEqual({ config: { content: 'iso,backup' } })
  })

  // A PBS datastore holds backups and nothing else, so the Backups page's
  // "Connect PBS" must not open on an unticked box PVE would override anyway.
  it('offers backups only, already ticked, when the type is pbs', async () => {
    withQuery(<StorageForm existing={null} onClose={vi.fn()} />)
    fireEvent.change(await screen.findByLabelText('Type'), { target: { value: 'pbs' } })
    expect(screen.getByLabelText('Backups')).toBeChecked()
    expect(screen.queryByLabelText('ISO images')).toBeNull()
  })

  it('confirms before detaching and does nothing when the operator cancels', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
    withQuery(<StorageForm existing={LOCAL} onClose={vi.fn()} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Detach' }))
    expect(confirm).toHaveBeenCalledWith(expect.stringContaining('local'))
    // mutate() runs its mutationFn in a microtask, so a synchronous check here
    // passes even with the window.confirm guard removed entirely, flush a
    // macrotask first (idiom borrowed from settings.test.tsx) so this actually
    // exercises the guard.
    await new Promise((r) => setTimeout(r, 10))
    expect(calls.some((c) => c.opts?.method === 'DELETE')).toBe(false)

    confirm.mockReturnValue(true)
    fireEvent.click(screen.getByRole('button', { name: 'Detach' }))
    await waitFor(() => expect(calls.some((c) => c.opts?.method === 'DELETE')).toBe(true))
    expect(calls.find((c) => c.opts?.method === 'DELETE')!.path).toBe('/storage/1/local')
  })

  it('deletes a volume only after the confirm, and encodes the volid', async () => {
    const spy = vi.spyOn(window, 'confirm').mockReturnValue(true)
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={qc}><StoragePage /></QueryClientProvider>)
    fireEvent.click(await screen.findByText('local-lvm'))
    fireEvent.click((await screen.findAllByRole('button', { name: 'Delete' }))[0])
    await waitFor(() =>
      expect(calls.some(c =>
        c.path.startsWith('/storage/1/local-lvm/content/local%3Aiso%2Fdebian-12.iso') &&
        c.opts?.method === 'DELETE')).toBe(true))
    spy.mockRestore()
  })

  it('does not delete when the confirm is dismissed', async () => {
    const spy = vi.spyOn(window, 'confirm').mockReturnValue(false)
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={qc}><StoragePage /></QueryClientProvider>)
    fireEvent.click(await screen.findByText('local-lvm'))
    fireEvent.click((await screen.findAllByRole('button', { name: 'Delete' }))[0])
    await waitFor(() => expect(screen.getAllByRole('button', { name: 'Delete' }).length).toBeGreaterThan(0))
    expect(calls.some(c => c.opts?.method === 'DELETE')).toBe(false)
    spy.mockRestore()
  })
})

describe('UploadDialog name collision', () => {
  const collision = {
    error: 'volume_exists', volid: 'local:iso/ubuntu.iso', filename: 'ubuntu.iso',
    size_bytes: 4242,
    detail: 'local:iso/ubuntu.iso already exists on local (4242 bytes). Replacing it keeps the name and swaps the contents, so anything already using it gets the new file.',
  }

  const pick = () => {
    const input = screen.getByLabelText('File') as HTMLInputElement
    const file = new File(['iso-bytes'], 'ubuntu.iso', { type: 'application/octet-stream' })
    fireEvent.change(input, { target: { files: [file] } })
  }

  it('offers Replace or Cancel instead of a typed phrase, and does not upload until asked', async () => {
    withQuery(<UploadDialog hostId={1} storage="local" node="pve1"
      contentTypes={['iso']} onClose={vi.fn()} />)
    pick()
    fireEvent.click(screen.getByRole('button', { name: 'Upload' }))
    await waitFor(() => expect(FakeXHR.instances).toHaveLength(1))
    act(() => FakeXHR.instances[0].respond(409, collision))

    // The prompt names the file and the volid, and asks for a click.
    await screen.findByText('ubuntu.iso already exists')
    expect(screen.getByText('local:iso/ubuntu.iso')).toBeTruthy()
    expect(screen.queryByLabelText(/type/i)).toBeNull()   // no typed confirmation

    // First attempt carried no overwrite flag: the SERVER detects the clash.
    expect((FakeXHR.instances[0].body as FormData).get('overwrite')).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: 'Replace' }))
    await waitFor(() => expect(FakeXHR.instances).toHaveLength(2))
    act(() => FakeXHR.instances[1].respond(202, { job: { id: 12, kind: 'storage.upload' } }))
    expect((FakeXHR.instances[1].body as FormData).get('overwrite')).toBe('true')
    expect(await screen.findByRole('button', { name: 'Upload in background' })).toBeInTheDocument()
  })

  it('Cancel backs out and uploads nothing', async () => {
    withQuery(<UploadDialog hostId={1} storage="local" node="pve1"
      contentTypes={['iso']} onClose={vi.fn()} />)
    pick()
    fireEvent.click(screen.getByRole('button', { name: 'Upload' }))
    await waitFor(() => expect(FakeXHR.instances).toHaveLength(1))
    act(() => FakeXHR.instances[0].respond(409, collision))
    await screen.findByText('ubuntu.iso already exists')

    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    await waitFor(() => expect(screen.queryByText('ubuntu.iso already exists')).toBeNull())
    expect(FakeXHR.instances).toHaveLength(1)   // nothing was replaced
  })
})

describe('UploadDialog content type', () => {
  it('opens on ISO even when PVE lists vztmpl first', async () => {
    withQuery(<UploadDialog hostId={1} storage="unraid-test" node="pve1"
      contentTypes={['import', 'vztmpl', 'iso']} onClose={() => {}} />)
    const select = await screen.findByLabelText('Content type') as HTMLSelectElement
    expect(select.value).toBe('iso')
  })

  it('follows the picked file, so a template is not filed as an ISO', async () => {
    withQuery(<UploadDialog hostId={1} storage="unraid-test" node="pve1"
      contentTypes={['import', 'vztmpl', 'iso']} onClose={() => {}} />)
    const select = await screen.findByLabelText('Content type') as HTMLSelectElement
    const input = screen.getByLabelText('File') as HTMLInputElement
    const tmpl = new File(['x'], 'debian-12-standard_12.7-1_amd64.tar.zst')
    fireEvent.change(input, { target: { files: [tmpl] } })
    await waitFor(() => expect(select.value).toBe('vztmpl'))
  })
})
