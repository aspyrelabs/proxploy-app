import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { api as apiMock } from '../api/client'
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
type HostRow = {
  id: number; name: string
  default_container_storage?: string | null
  default_template_storage?: string | null
}

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

/** A host that has already answered the storage question once: two real
 *  rootdir candidates exist, but Host.default_container_storage /
 *  default_template_storage are already set, so Default must show the
 *  answer rather than ask again. */
async function mockHostWithRememberedStorage(remembered: { container: string; template: string }) {
  const { api } = await import('../api/client')
  const hosts: HostRow[] = [
    { id: 1, name: 'host-01', default_container_storage: remembered.container,
      default_template_storage: remembered.template },
    { id: 2, name: 'host-02' },
  ]
  const rows: StorageRow[] = [
    { host_id: 1, node: 'pve', storage: 'local', content: ['vztmpl'] },
    { host_id: 1, node: 'pve', storage: 'lvm-a', content: ['rootdir'] },
    { host_id: 1, node: 'pve', storage: 'lvm-b', content: ['rootdir'] },
  ]
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

/** Reads the args of the last POST to the install endpoint, whatever slug
 *  it targeted, without asserting on the slug itself. */
function capturedSubmit() {
  const calls = vi.mocked(apiMock).mock.calls
  const call = calls.find(([path]) => String(path).endsWith('/install'))
  if (!call) throw new Error('no install call captured')
  return JSON.parse((call[1] as { body: string }).body)
}

/** Fills every field the Advanced block exposes (as of Task 10: the base
 *  fields plus cpu/ram/disk/os/version/hostname/unprivileged) and submits.
 *  Storage pickers are deliberately left untouched: Task 9 already covers
 *  them and an unset picker is a valid, honest "let the backend decide". */
async function fillEveryField() {
  fireEvent.change(screen.getByPlaceholderText('App name'), { target: { value: 'redis-1' } })
  fireEvent.change(screen.getByPlaceholderText('Container ID (CTID)'), { target: { value: '150' } })
  // Exact matches, not regexes: the Advanced radio's own subtitle copy
  // ("Customize vCPU, RAM, disk, storage and more...") contains these same
  // words inside its wrapping <label>, so a case-insensitive substring match
  // finds two labelled elements and getByLabelText throws.
  fireEvent.change(screen.getByLabelText('vCPU'), { target: { value: '4' } })
  fireEvent.change(screen.getByLabelText('RAM (MB)'), { target: { value: '4096' } })
  fireEvent.change(screen.getByLabelText('Disk (GB)'), { target: { value: '20' } })
  fireEvent.change(screen.getByLabelText('OS'), { target: { value: 'ubuntu' } })
  fireEvent.change(screen.getByLabelText('OS version'), { target: { value: '24.04' } })
  fireEvent.change(screen.getByLabelText('Hostname'), { target: { value: 'redis-custom' } })
  fireEvent.click(screen.getByLabelText(/unprivileged/i))
  fireEvent.click(screen.getByRole('checkbox', { name: /runs as root/i }))
  fireEvent.click(screen.getByRole('button', { name: 'Install' }))
  await waitFor(() => expect(capturedSubmit()).toBeTruthy())
}

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

  it('emits only variable names build.func actually reads', async () => {
    // Pinned from build.func at the catalog's upstream_sha. A typo or an
    // upstream rename must fail here rather than silently sending an
    // override into the void.
    const KNOWN = new Set([
      'brg', 'container_storage', 'cpu', 'ctid', 'disk', 'fuse', 'gateway',
      'gpu', 'hostname', 'mtu', 'nesting', 'net', 'os', 'pw', 'ram',
      'searchdomain', 'ssh', 'ssh_authorized_key', 'tags', 'template_storage',
      'timezone', 'unprivileged', 'version', 'vlan',
    ])
    vi.mocked(apiMock).mockImplementation((path: string) => {
      if (path === '/catalog/redis') return Promise.resolve({
        slug: 'redis', name: 'Redis', default_cpu: 1, default_ram_mb: 1024,
        default_disk_gb: 4, default_os: 'debian', default_os_version: '13',
        installable: true, raw: { install_script: 'msg_ok done' },
      })
      if (path === '/hosts') return Promise.resolve([{ id: 1, name: 'host-01' }])
      if (path === '/storage') return Promise.resolve([])
      if (path === '/catalog/redis/install') return Promise.resolve({
        job: { id: 9, kind: 'app.install', progress_pct: null },
      })
      return Promise.resolve(null)
    })
    renderDialog()
    await openAdvanced()
    await fillEveryField()
    const sent = capturedSubmit().overrides
    for (const key of Object.keys(sent)) expect(KNOWN.has(key)).toBe(true)
  })

  it('prefills from the script-parsed defaults', async () => {
    const qc = new QueryClient()
    vi.mocked(apiMock).mockImplementation((path: string) => {
      if (path === '/catalog/dockge') return Promise.resolve({
        slug: 'dockge', name: 'Dockge', default_cpu: 2, default_ram_mb: 2048,
        default_disk_gb: 18, default_os: 'debian', default_os_version: '13',
        installable: true, raw: { install_script: 'msg_ok done' },
      })
      if (path === '/hosts') return Promise.resolve([{ id: 1, name: 'host-01' }])
      if (path === '/storage') return Promise.resolve([])
      return Promise.resolve(null)
    })
    render(
      <QueryClientProvider client={qc}>
        <InstallDialog slug="dockge" onClose={vi.fn()} />
      </QueryClientProvider>,
    )
    await openAdvanced()
    // not metadata's 0 (raw.metadata.install_methods[].resources disagrees
    // with the script-parsed columns for this exact slug; see Task 7).
    expect(screen.getByLabelText(/RAM/i)).toHaveValue(2048)
  })

  it('Default asks the storage question only when there is a real choice', async () => {
    // host-01 in DEFAULT_STORAGE has exactly one rootdir candidate
    // ('local-lvm'): one candidate is not a choice, so Default stays one
    // click. It still shows what it resolved to, per "remembering must
    // never become deciding silently" -- that applies to a sole candidate
    // too, not only a remembered value.
    await mockStorage()
    renderDialog()
    await waitFor(() => expect(screen.getByRole('combobox', { name: /host/i })).toBeInTheDocument())
    await selectHost('host-01')

    await waitFor(() => expect(screen.getByText(/local-lvm/)).toBeInTheDocument())
    expect(screen.queryByLabelText(/Container storage/i)).not.toBeInTheDocument()
  })

  it('Default asks when the host has two pools, because there is no honest default', async () => {
    await mockStorage([
      { host_id: 1, node: 'pve', storage: 'local', content: ['vztmpl'] },
      { host_id: 1, node: 'pve', storage: 'lvm-a', content: ['rootdir'] },
      { host_id: 1, node: 'pve', storage: 'lvm-b', content: ['rootdir'] },
    ])
    renderDialog()
    await waitFor(() => expect(screen.getByRole('combobox', { name: /host/i })).toBeInTheDocument())
    await selectHost('host-01')

    expect(await screen.findByLabelText(/Container storage/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Install' })).toBeDisabled()

    // Fill in everything else the button needs; it must stay disabled until
    // the ambiguous pool is actually chosen -- this is the one question
    // Default is allowed to ask, and it is not optional.
    fireEvent.change(screen.getByPlaceholderText('App name'), { target: { value: 'redis-1' } })
    fireEvent.click(screen.getByRole('checkbox'))
    expect(screen.getByRole('button', { name: 'Install' })).toBeDisabled()

    fireEvent.change(screen.getByLabelText(/Container storage/i), { target: { value: 'lvm-b' } })
    expect(screen.getByRole('button', { name: 'Install' })).toBeEnabled()
  })

  it('shows the pools it will use, so remembering never becomes deciding silently', async () => {
    await mockHostWithRememberedStorage({ container: 'lvm-a', template: 'local' })
    renderDialog()
    await waitFor(() => expect(screen.getByRole('combobox', { name: /host/i })).toBeInTheDocument())
    await selectHost('host-01')

    // Displayed as text, not asked as a question -- even though this host
    // genuinely has two rootdir candidates (lvm-a, lvm-b).
    await waitFor(() => expect(screen.getByText(/lvm-a/)).toBeInTheDocument())
    expect(screen.queryByLabelText(/Container storage/i)).not.toBeInTheDocument()
  })
})
