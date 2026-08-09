import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const LOCAL = {
  host_id: 1, host_name: 'host-01', node: 'pve1', storage: 'local', type: 'dir',
  content: ['iso', 'vztmpl', 'backup'], shared: false, status: 'available',
  used_bytes: 100, total_bytes: 400, used_pct: 25.0,
}
// Second row + its content listing exist only for the delete-volume tests
// (Step 8b), which click through StoragePage to a real content row rather
// than mounting VolumeTable directly.
const LOCAL_LVM = {
  host_id: 1, host_name: 'host-01', node: 'pve1', storage: 'local-lvm', type: 'lvmthin',
  content: ['iso'], shared: false, status: 'available',
  used_bytes: 50, total_bytes: 200, used_pct: 25.0,
}
const ISO_VOL = {
  volid: 'local:iso/debian-12.iso', format: 'iso', size: 700, used: 0,
  vmid: null, ctime: 1730000000, content: 'iso', notes: null, verification: null,
}

let features: Record<string, boolean> = { 'storage.manage': true }
const calls: { path: string; opts?: any }[] = []

vi.mock('../api/client', () => ({
  api: vi.fn((path: string, opts?: any) => {
    calls.push({ path, opts })
    if (path === '/entitlements') {
      return Promise.resolve({ tier: 'pro', features, grace: null, clock_skew: false })
    }
    if (path === '/hosts') return Promise.resolve([{ id: 1, name: 'host-01' }])
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
  ApiError: class extends Error {},
}))

vi.mock('@tanstack/react-router', async (orig) => ({
  ...(await orig() as object),
  Link: ({ children }: { children?: unknown }) => <a>{children as never}</a>,
  useNavigate: () => () => {},
  useSearch: () => ({}),
}))

import { StorageForm } from '../components/StorageForm'
import { UploadDialog } from '../components/UploadDialog'
import { StoragePage } from '../routes/storage'

const withQuery = (ui: React.ReactNode) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

beforeEach(() => {
  calls.length = 0
  features = { 'storage.manage': true }
  document.cookie = 'pp_csrf=csrf-token-abc'
})
afterEach(() => { vi.restoreAllMocks() })

describe('UploadDialog', () => {
  it('POSTs multipart with credentials + CSRF and no Content-Type override', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true, status: 202, json: () => Promise.resolve({ job: { id: 9, kind: 'storage.upload' } }),
    })
    vi.stubGlobal('fetch', fetchMock)

    withQuery(<UploadDialog hostId={1} storage="local" node="pve1"
      contentTypes={['iso', 'vztmpl', 'backup']} onClose={vi.fn()} />)

    const input = screen.getByLabelText('File') as HTMLInputElement
    const file = new File(['iso-bytes'], 'ubuntu.iso', { type: 'application/octet-stream' })
    fireEvent.change(input, { target: { files: [file] } })
    fireEvent.click(screen.getByRole('button', { name: 'Upload' }))

    await waitFor(() => expect(fetchMock).toHaveBeenCalled())
    const [url, opts] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/v1/storage/1/local/content')
    expect(opts.method).toBe('POST')
    expect(opts.credentials).toBe('include')
    expect(opts.headers['X-CSRF-Token']).toBe('csrf-token-abc')
    // the whole reason this is not api(): a Content-Type here kills the boundary
    expect(opts.headers['Content-Type']).toBeUndefined()
    expect(opts.body).toBeInstanceOf(FormData)
    expect((opts.body as FormData).get('content')).toBe('iso')
    expect((opts.body as FormData).get('node')).toBe('pve1')
    expect((opts.body as FormData).get('file')).toBe(file)
  })

  it('swaps the body for the job log once the upload returns a job', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true, status: 202, json: () => Promise.resolve({ job: { id: 9, kind: 'storage.upload' } }),
    }))
    withQuery(<UploadDialog hostId={1} storage="local" node="pve1"
      contentTypes={['iso']} onClose={vi.fn()} />)
    fireEvent.change(screen.getByLabelText('File'),
      { target: { files: [new File(['x'], 'a.iso')] } })
    fireEvent.click(screen.getByRole('button', { name: 'Upload' }))
    expect(await screen.findByRole('button', { name: 'Close' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Upload' })).toBeNull()
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
    fireEvent.change(screen.getByLabelText('Content'), { target: { value: 'iso,vztmpl' } })
    fireEvent.click(screen.getByRole('button', { name: 'Attach' }))

    await waitFor(() => expect(calls.some((c) => c.path === '/storage' && c.opts?.method === 'POST')).toBe(true))
    const post = calls.find((c) => c.path === '/storage' && c.opts?.method === 'POST')!
    expect(JSON.parse(post.opts.body)).toEqual({
      host_id: 1, storage: 'nfs-media', type: 'nfs',
      config: { server: '10.0.0.30', export: '/media', content: 'iso,vztmpl' },
    })
  })

  it('veils the form when storage.manage is off, and never before entitlements resolve', async () => {
    features = {}
    withQuery(<StorageForm existing={null} onClose={vi.fn()} />)
    // has() is false until the first fetch resolves, gating on !has() alone
    // would veil this for every plan during load.
    expect(screen.queryByText('Unlock Pro')).toBeNull()
    expect(await screen.findByText('Unlock Pro')).toBeInTheDocument()
  })

  it('PATCHes only the fields the operator filled in edit mode', async () => {
    withQuery(<StorageForm existing={LOCAL} onClose={vi.fn()} />)
    fireEvent.change(await screen.findByLabelText('Content'), { target: { value: 'iso,backup' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(calls.some((c) => c.opts?.method === 'PATCH')).toBe(true))
    const patch = calls.find((c) => c.opts?.method === 'PATCH')!
    expect(patch.path).toBe('/storage/1/local')
    expect(JSON.parse(patch.opts.body)).toEqual({ config: { content: 'iso,backup' } })
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
