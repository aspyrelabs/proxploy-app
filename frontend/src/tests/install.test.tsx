import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { InstallDialog } from '../components/InstallDialog'
import { FakeEventSource, installFakeEventSource } from './fakeEventSource'

vi.mock('../api/client', () => ({ api: vi.fn() }))

function renderDialog() {
  const qc = new QueryClient()
  return render(
    <QueryClientProvider client={qc}>
      <InstallDialog slug="redis" onClose={vi.fn()} />
    </QueryClientProvider>,
  )
}

type StorageRow = { host_id: number; node: string; storage: string; content: string[] }
type HostRow = { id: number; name: string }

const DEFAULT_HOSTS: HostRow[] = [{ id: 1, name: 'host-01' }, { id: 2, name: 'host-02' }]
// host 1 carries a vztmpl-only pool ('local') and a rootdir-only pool
// ('local-lvm'); host 2 carries a single pool good for both, used by the
// re-query test to prove the candidate list is keyed on the target host.
const DEFAULT_STORAGE: StorageRow[] = [
  { host_id: 1, node: 'pve', storage: 'local', content: ['vztmpl', 'iso'] },
  { host_id: 1, node: 'pve', storage: 'local-lvm', content: ['rootdir'] },
  { host_id: 2, node: 'pve2', storage: 'host02-lvm', content: ['rootdir', 'vztmpl'] },
]

async function mockStorage(rows: StorageRow[] = DEFAULT_STORAGE, hosts: HostRow[] = DEFAULT_HOSTS) {
  const { api } = await import('../api/client')
  vi.mocked(api).mockImplementation((path: string) => {
    if (path === '/catalog/redis') return Promise.resolve({
      slug: 'redis', name: 'Redis', default_cpu: 1, default_ram_mb: 1024,
      default_disk_gb: 4, installable: true, raw: { install_script: 'msg_ok done' },
    })
    if (path === '/hosts') return Promise.resolve(hosts)
    if (path === '/storage') return Promise.resolve(rows)
    return Promise.resolve(null)
  })
}

async function openAdvanced() {
  await waitFor(() => expect(screen.getByRole('radio', { name: /advanced/i })).toBeInTheDocument())
  fireEvent.click(screen.getByRole('radio', { name: /advanced/i }))
  // The pickers need a target host to filter pools for; select the first one.
  fireEvent.change(screen.getByRole('combobox', { name: /host/i }), { target: { value: '1' } })
}

async function selectHost(name: string) {
  const hostSelect = screen.getByRole('combobox', { name: /host/i })
  const option = within(hostSelect).getByText(name) as HTMLOptionElement
  fireEvent.change(hostSelect, { target: { value: option.value } })
}

function optionsOf(labelText: string) {
  const select = screen.getByLabelText(labelText) as HTMLSelectElement
  return within(select).getAllByRole('option')
    .map((o) => (o as HTMLOptionElement).value)
    .filter((v) => v !== '')
}
const containerOptions = () => optionsOf('Container storage')
const templateOptions = () => optionsOf('Template storage')

/** Fills the form and submits, up to (not including) whatever install-job
 *  response the test's own api mock returns. */
async function startInstall() {
  await waitFor(() => expect(screen.getByText(/runs as root on/i)).toBeInTheDocument())
  fireEvent.change(screen.getByRole('combobox'), { target: { value: '1' } })
  fireEvent.change(screen.getByPlaceholderText('App name'), { target: { value: 'redis-1' } })
  fireEvent.change(screen.getByPlaceholderText('Container ID (CTID)'), { target: { value: '105' } })
  fireEvent.click(screen.getByRole('checkbox'))
  fireEvent.click(screen.getByRole('button', { name: 'Install' }))
}

describe('InstallDialog', () => {
  it('disables Install until consent is checked, then submits with consent:true', async () => {
    const { api } = await import('../api/client')
    vi.mocked(api).mockImplementation((path: string) => {
      if (path === '/catalog/redis') return Promise.resolve({
        slug: 'redis', name: 'Redis', default_cpu: 1, default_ram_mb: 1024,
        default_disk_gb: 4, installable: true, raw: { install_script: 'msg_ok done' },
      })
      if (path === '/hosts') return Promise.resolve([{ id: 1, name: 'host-01' }])
      if (path === '/catalog/redis/install') return Promise.resolve({ job: { id: 9, kind: 'app.install' } })
      return Promise.resolve(null)
    })

    renderDialog()
    await waitFor(() => expect(screen.getByText(/runs as root on/i)).toBeInTheDocument())
    const installBtn = screen.getByRole('button', { name: 'Install' })
    expect(installBtn).toBeDisabled()

    // Fill host/name/ctid, button must stay disabled until consent is also checked.
    fireEvent.change(screen.getByRole('combobox'), { target: { value: '1' } })
    fireEvent.change(screen.getByPlaceholderText('App name'), { target: { value: 'redis-1' } })
    fireEvent.change(screen.getByPlaceholderText('Container ID (CTID)'), { target: { value: '105' } })
    expect(installBtn).toBeDisabled()

    fireEvent.click(screen.getByRole('checkbox'))
    expect(installBtn).toBeEnabled()
    fireEvent.click(installBtn)

    await waitFor(() => expect(api).toHaveBeenCalledWith('/catalog/redis/install', expect.objectContaining({
      method: 'POST',
      body: expect.stringContaining('"consent":true'),
    })))
  })

  it('opens on Default, and Advanced reveals the container customization block', async () => {
    const { api } = await import('../api/client')
    vi.mocked(api).mockImplementation((path: string) => {
      if (path === '/catalog/redis') return Promise.resolve({
        slug: 'redis', name: 'Redis', default_cpu: 1, default_ram_mb: 1024,
        default_disk_gb: 4, installable: true, raw: { install_script: 'msg_ok done' },
      })
      if (path === '/hosts') return Promise.resolve([{ id: 1, name: 'host-01' }])
      return Promise.resolve(null)
    })

    renderDialog()
    await waitFor(() => expect(screen.getByRole('radio', { name: /default/i })).toBeInTheDocument())

    // Default asks nothing that has an honest default: no expanded block yet.
    expect(screen.getByRole('radio', { name: /default/i })).toBeChecked()
    expect(screen.queryByText('Container customization')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('radio', { name: /advanced/i }))
    expect(screen.getByText('Container customization')).toBeInTheDocument()
  })

  it('does not require a CTID to submit', async () => {
    const { api } = await import('../api/client')
    vi.mocked(api).mockImplementation((path: string) => {
      if (path === '/catalog/redis') return Promise.resolve({
        slug: 'redis', name: 'Redis', default_cpu: 1, default_ram_mb: 1024,
        default_disk_gb: 4, installable: true, raw: { install_script: 'msg_ok done' },
      })
      if (path === '/hosts') return Promise.resolve([{ id: 1, name: 'host-01' }])
      return Promise.resolve(null)
    })

    renderDialog()
    await waitFor(() => expect(screen.getByText(/runs as root on/i)).toBeInTheDocument())

    fireEvent.change(screen.getByRole('combobox'), { target: { value: '1' } })
    fireEvent.change(screen.getByPlaceholderText('App name'), { target: { value: 'redis-1' } })
    fireEvent.click(screen.getByRole('checkbox'))

    // No CTID typed, and Install is still enabled: blank means the node
    // assigns the next free id (InstallIn.ctid).
    expect(screen.getByPlaceholderText('Container ID (CTID)')).toHaveValue('')
    expect(screen.getByRole('button', { name: 'Install' })).toBeEnabled()
  })

  // services/appstore.py::run_install only calls ctx.progress(80) then (100):
  // progress_pct is null on the freshly-enqueued job this mutation returns,
  // so no ring should appear until the job actually reports something.
  it('shows no ring until the install job reports progress, then reflects a live update', async () => {
    const restore = installFakeEventSource()
    const { api } = await import('../api/client')
    vi.mocked(api).mockImplementation((path: string) => {
      if (path === '/catalog/redis') return Promise.resolve({
        slug: 'redis', name: 'Redis', default_cpu: 1, default_ram_mb: 1024,
        default_disk_gb: 4, installable: true, raw: { install_script: 'msg_ok done' },
      })
      if (path === '/hosts') return Promise.resolve([{ id: 1, name: 'host-01' }])
      if (path === '/catalog/redis/install') return Promise.resolve({
        job: { id: 9, kind: 'app.install', progress_pct: null },
      })
      if (path === '/jobs/9/events') return Promise.resolve([])
      return Promise.resolve(null)
    })

    renderDialog()
    await startInstall()

    await screen.findByText(/installing/i)
    expect(screen.queryByRole('status')).toBeNull()

    FakeEventSource.last.emit('progress', { pct: 55 })
    await waitFor(() => expect(screen.getByRole('status')).toHaveAttribute(
      'aria-label', expect.stringContaining('55 percent')))

    restore()
  })

  // A job row already carrying progress (the response to the install POST
  // itself, however unlikely mid-creation) has to seed the ring rather than
  // flash zero for a tick before the first live frame arrives.
  it('seeds the ring from the job row instead of starting at zero', async () => {
    const { api } = await import('../api/client')
    vi.mocked(api).mockImplementation((path: string) => {
      if (path === '/catalog/redis') return Promise.resolve({
        slug: 'redis', name: 'Redis', default_cpu: 1, default_ram_mb: 1024,
        default_disk_gb: 4, installable: true, raw: { install_script: 'msg_ok done' },
      })
      if (path === '/hosts') return Promise.resolve([{ id: 1, name: 'host-01' }])
      if (path === '/catalog/redis/install') return Promise.resolve({
        job: { id: 9, kind: 'app.install', progress_pct: 45 },
      })
      if (path === '/jobs/9/events') return Promise.resolve([])
      return Promise.resolve(null)
    })

    renderDialog()
    await startInstall()

    await waitFor(() => expect(screen.getByRole('status')).toHaveAttribute(
      'aria-label', expect.stringContaining('45 percent')))
  })

  it('offers only rootdir pools for the container and vztmpl for the template', async () => {
    await mockStorage([
      { host_id: 1, node: 'pve', storage: 'local', content: ['vztmpl', 'iso'] },
      { host_id: 1, node: 'pve', storage: 'local-lvm', content: ['rootdir'] },
    ])
    renderDialog()
    await openAdvanced()

    // A vztmpl-only pool as the rootfs fails at pct create with a raw Proxmox
    // error, after this form said it was fine.
    await waitFor(() => expect(containerOptions()).toEqual(['local-lvm']))
    expect(templateOptions()).toEqual(['local'])
  })

  it('re-queries candidates when the target host changes', async () => {
    await mockStorage()
    renderDialog()
    await openAdvanced()
    await waitFor(() => expect(containerOptions()).toEqual(['local-lvm']))

    await selectHost('host-02')
    await waitFor(() => expect(containerOptions()).toEqual(['host02-lvm']))
  })
})
