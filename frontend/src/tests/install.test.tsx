import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api as apiMock } from '../api/client'
import { InstallDialog } from '../components/InstallDialog'
import { knownPool } from '../components/install/pools'
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

type StorageRow = {
  host_id: number; node: string; storage: string; content: string[]; status?: string
  shared?: boolean
}
type HostRow = {
  id: number; name: string; node_name?: string
  default_container_storage?: string | null
  default_template_storage?: string | null
  install_consent_at?: string | null
}

/** GET /storage always carries `status` (api/storage.py::_row) and the dialog
 *  only offers available pools, so a fixture row without one would be a row
 *  the real API never sends. Defaulted here so each test only spells out what
 *  it is actually about. */
const withStatus = (rows: StorageRow[]) =>
  rows.map((r) => ({ status: 'available', ...r }))

const DEFAULT_HOSTS: HostRow[] = [
  { id: 1, name: 'host-01', node_name: 'pve' },
  { id: 2, name: 'host-02', node_name: 'pve2' },
]
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
    if (path === '/storage') return Promise.resolve(withStatus(rows))
    if (path === '/catalog/redis/install') return Promise.resolve({
      job: { id: 9, kind: 'app.install', progress_pct: null },
    })
    if (path === '/jobs/9/events') return Promise.resolve([])
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
    { id: 1, name: 'host-01', node_name: 'pve',
      default_container_storage: remembered.container,
      default_template_storage: remembered.template },
    { id: 2, name: 'host-02', node_name: 'pve2' },
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
    if (path === '/storage') return Promise.resolve(withStatus(rows))
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
 *  it targeted, without asserting on the slug itself.
 *
 *  Scanned from the END, and paired with the beforeEach that clears
 *  mock.calls. Without either, `mock.calls` accumulates for the whole file
 *  and a `find` from the front returns the FIRST install this suite ever
 *  made, which belongs to another test entirely: that is how the overrides
 *  assertions here used to read an unrelated `{}` and pass no matter what
 *  this dialog sent. */
function capturedSubmit() {
  const calls = vi.mocked(apiMock).mock.calls
  const call = [...calls].reverse().find(([path]) => String(path).endsWith('/install'))
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
  // mock.calls otherwise accumulates across the whole file, and capturedSubmit
  // would read a request an earlier test made instead of failing when this
  // dialog sent nothing. Implementations survive clearAllMocks; only the
  // recorded calls go.
  beforeEach(() => { vi.clearAllMocks() })

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
    // Asserted as an exact object, not key-by-key against KNOWN: an
    // `overrides` that lost every answer the operator gave is `{}`, and a
    // membership loop over `{}` passes while asserting nothing at all.
    // Storage is absent because fillEveryField leaves both pickers alone.
    expect(sent).toEqual({
      cpu: '4', ram: '4096', disk: '20', os: 'ubuntu', version: '24.04',
      hostname: 'redis-custom', unprivileged: '1',
    })
    for (const key of Object.keys(sent)) expect(KNOWN.has(key)).toBe(true)
  })

  it('withholds unprivileged entirely until the operator toggles it', async () => {
    // Not every ct script declares var_unprivileged="1": one declaring "0"
    // gets overruled by a checkbox the operator never touched, purely because
    // they opened Advanced.
    await mockStorage([])
    renderDialog()
    await openAdvanced()
    fireEvent.change(screen.getByPlaceholderText('App name'), { target: { value: 'redis-1' } })
    fireEvent.change(screen.getByLabelText('vCPU'), { target: { value: '4' } })
    fireEvent.click(screen.getByRole('checkbox', { name: /runs as root/i }))
    fireEvent.click(screen.getByRole('button', { name: 'Install' }))

    await waitFor(() => expect(capturedSubmit()).toBeTruthy())
    // ram/disk/hostname ride along because Advanced sends whatever those
    // fields DISPLAY, and they display the entry's script-parsed defaults.
    // `unprivileged` has no such parsed default, so it is the one key that
    // must be missing.
    expect(capturedSubmit().overrides).toEqual({
      cpu: '4', ram: '1024', disk: '4', hostname: 'redis-1',
    })
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

  it('sends the pool the operator picked in Default mode', async () => {
    // The whole point of the one question Default is allowed to ask: the
    // answer has to reach the request, or resolve_storage_pools refuses on
    // exactly the ambiguity the operator just resolved.
    await mockStorage([
      { host_id: 1, node: 'pve', storage: 'local', content: ['vztmpl'] },
      { host_id: 1, node: 'pve', storage: 'lvm-a', content: ['rootdir'] },
      { host_id: 1, node: 'pve', storage: 'lvm-b', content: ['rootdir'] },
    ])
    renderDialog()
    await waitFor(() => expect(screen.getByRole('combobox', { name: /host/i })).toBeInTheDocument())
    await selectHost('host-01')

    fireEvent.change(await screen.findByLabelText(/Container storage/i), { target: { value: 'lvm-b' } })
    fireEvent.change(screen.getByPlaceholderText('App name'), { target: { value: 'redis-1' } })
    fireEvent.click(screen.getByRole('checkbox', { name: /runs as root/i }))
    fireEvent.click(screen.getByRole('button', { name: 'Install' }))

    await waitFor(() => expect(capturedSubmit()).toBeTruthy())
    expect(capturedSubmit().overrides.container_storage).toBe('lvm-b')
  })

  it('asks about the template pool too, and sends that answer', async () => {
    // One rootdir pool and two vztmpl pools ('local' plus any NFS/dir storage
    // carrying vztmpl) is an ordinary Proxmox layout. Default used to have no
    // field for it at all, so every install on such a host failed in
    // resolve_storage_pools and Default could never fix itself.
    await mockStorage([
      { host_id: 1, node: 'pve', storage: 'lvm-a', content: ['rootdir'] },
      { host_id: 1, node: 'pve', storage: 'local', content: ['vztmpl'] },
      { host_id: 1, node: 'pve', storage: 'nas', content: ['vztmpl', 'iso'] },
    ])
    renderDialog()
    await waitFor(() => expect(screen.getByRole('combobox', { name: /host/i })).toBeInTheDocument())
    await selectHost('host-01')

    const templates = await screen.findByLabelText(/Template storage/i)
    fireEvent.change(screen.getByPlaceholderText('App name'), { target: { value: 'redis-1' } })
    fireEvent.click(screen.getByRole('checkbox', { name: /runs as root/i }))
    // The rootdir side is settled (one candidate), so this is the only thing
    // still holding the button.
    expect(screen.getByRole('button', { name: 'Install' })).toBeDisabled()

    fireEvent.change(templates, { target: { value: 'nas' } })
    expect(screen.getByRole('button', { name: 'Install' })).toBeEnabled()
    fireEvent.click(screen.getByRole('button', { name: 'Install' }))

    await waitFor(() => expect(capturedSubmit()).toBeTruthy())
    expect(capturedSubmit().overrides.template_storage).toBe('nas')
  })

  it('counts one pool once, however many nodes report it', async () => {
    // GET /storage keys non-shared datastores by (host, node, storage), so a
    // 3-node cluster with the usual identical local names answers 'local-lvm'
    // three times. The backend queries host.node_name alone and sees one.
    await mockStorage([
      { host_id: 1, node: 'pve', storage: 'local-lvm', content: ['rootdir'] },
      { host_id: 1, node: 'pve2', storage: 'local-lvm', content: ['rootdir'] },
      { host_id: 1, node: 'pve3', storage: 'local-lvm', content: ['rootdir'] },
      { host_id: 1, node: 'pve', storage: 'local', content: ['vztmpl'] },
    ])
    renderDialog()
    await waitFor(() => expect(screen.getByRole('combobox', { name: /host/i })).toBeInTheDocument())
    await selectHost('host-01')

    // One candidate is not a choice: shown, not asked.
    await waitFor(() => expect(screen.getByText(/local-lvm/)).toBeInTheDocument())
    expect(screen.queryByLabelText(/Container storage/i)).not.toBeInTheDocument()
  })

  it('never offers a pool the node is not serving', async () => {
    // _storage_pools drops anything not enabled and active. Offering one here
    // gets it chosen, remembered on the Host, and then every later Default
    // install fails with "no longer available", with no UI to clear it.
    await mockStorage([
      { host_id: 1, node: 'pve', storage: 'lvm-a', content: ['rootdir'], status: 'available' },
      { host_id: 1, node: 'pve', storage: 'lvm-dead', content: ['rootdir'], status: 'unavailable' },
      { host_id: 1, node: 'pve', storage: 'local', content: ['vztmpl'] },
    ])
    renderDialog()
    await openAdvanced()

    await waitFor(() => expect(containerOptions()).toEqual(['lvm-a']))
  })

  it('re-asks when a remembered pool is no longer a candidate', async () => {
    // A wrong or stale memory is otherwise permanent: the prompt used to be
    // gated on the column merely being set, and there is no PATCH field and
    // no other UI that can clear it.
    await mockStorage([
      { host_id: 1, node: 'pve', storage: 'lvm-a', content: ['rootdir'] },
      { host_id: 1, node: 'pve', storage: 'lvm-b', content: ['rootdir'] },
      { host_id: 1, node: 'pve', storage: 'local', content: ['vztmpl'] },
    ], [{ id: 1, name: 'host-01', node_name: 'pve', default_container_storage: 'lvm-gone' }])
    renderDialog()
    await waitFor(() => expect(screen.getByRole('combobox', { name: /host/i })).toBeInTheDocument())
    await selectHost('host-01')

    expect(await screen.findByLabelText(/Container storage/i)).toBeInTheDocument()
    expect(screen.queryByText(/lvm-gone/)).not.toBeInTheDocument()
  })

  it('offers a shared pool even when its row names a node other than the host\'s own', async () => {
    // backend/proxploy/api/storage.py::list_storage keys a shared datastore by
    // (host_id, storage) with no node component and keeps whichever row the
    // poller snapshot happened to see first, in raw /cluster/resources order.
    // For a shared pool visible on three nodes that row may legitimately name
    // a node other than host-01's own ('pve'). The old node filter dropped it
    // anyway, so no prompt rendered even though this host genuinely has two
    // rootdir pools.
    await mockStorage([
      { host_id: 1, node: 'pve2', storage: 'shared-a', content: ['rootdir'], shared: true },
      { host_id: 1, node: 'pve3', storage: 'shared-b', content: ['rootdir'], shared: true },
      { host_id: 1, node: 'pve', storage: 'local', content: ['vztmpl'] },
    ])
    renderDialog()
    await waitFor(() => expect(screen.getByRole('combobox', { name: /host/i })).toBeInTheDocument())
    await selectHost('host-01')

    fireEvent.change(await screen.findByLabelText(/Container storage/i), { target: { value: 'shared-b' } })
    fireEvent.change(screen.getByPlaceholderText('App name'), { target: { value: 'redis-1' } })
    fireEvent.click(screen.getByRole('checkbox', { name: /runs as root/i }))
    fireEvent.click(screen.getByRole('button', { name: 'Install' }))

    await waitFor(() => expect(capturedSubmit()).toBeTruthy())
    expect(capturedSubmit().overrides.container_storage).toBe('shared-b')
  })

  it('does not double-count a shared pool reported more than once', async () => {
    await mockStorage([
      { host_id: 1, node: 'pve2', storage: 'shared-a', content: ['rootdir'], shared: true },
      { host_id: 1, node: 'pve3', storage: 'shared-a', content: ['rootdir'], shared: true },
      { host_id: 1, node: 'pve', storage: 'local', content: ['vztmpl'] },
    ])
    renderDialog()
    await openAdvanced()

    // One real candidate is not a choice, even though the row appears twice.
    await waitFor(() => expect(containerOptions()).toEqual(['shared-a']))
  })

  it('re-asks a stale remembered pool even when exactly one valid candidate remains', async () => {
    // resolve_storage_pools raises whenever `remembered` is set and is not
    // among the candidates, REGARDLESS of how many candidates remain: a
    // remembered choice is never quietly swapped for the sole survivor. The
    // old knownPool fell through to "sole candidate" here, showing
    // "Storage: container lvm-b" as settled with no field to change it, and
    // the job then failed on the stale 'lvm-gone' name it never sent.
    await mockStorage([
      { host_id: 1, node: 'pve', storage: 'lvm-b', content: ['rootdir'] },
      { host_id: 1, node: 'pve', storage: 'local', content: ['vztmpl'] },
    ], [{ id: 1, name: 'host-01', node_name: 'pve', default_container_storage: 'lvm-gone' }])
    renderDialog()
    await waitFor(() => expect(screen.getByRole('combobox', { name: /host/i })).toBeInTheDocument())
    await selectHost('host-01')

    expect(await screen.findByLabelText(/Container storage/i)).toBeInTheDocument()
    // Never presented as a settled fact: the surviving pool must not appear
    // in the "Storage: ..." summary while the question is unanswered.
    expect(screen.queryByText(/Storage:.*lvm-b/)).not.toBeInTheDocument()

    fireEvent.change(screen.getByPlaceholderText('App name'), { target: { value: 'redis-1' } })
    fireEvent.click(screen.getByRole('checkbox', { name: /runs as root/i }))
    expect(screen.getByRole('button', { name: 'Install' })).toBeDisabled()

    fireEvent.change(screen.getByLabelText(/Container storage/i), { target: { value: 'lvm-b' } })
    expect(screen.getByRole('button', { name: 'Install' })).toBeEnabled()
    fireEvent.click(screen.getByRole('button', { name: 'Install' }))

    await waitFor(() => expect(capturedSubmit()).toBeTruthy())
    expect(capturedSubmit().overrides.container_storage).toBe('lvm-b')
  })

  it('will not submit while the storage snapshot cannot be read', async () => {
    // GET /storage is served from the poller snapshot, empty until the first
    // poll after a backend restart and absent on a 403. Empty candidate lists
    // then look exactly like "no question to ask", and the job fails with
    // "host has no storage carrying 'rootdir'".
    const { api } = await import('../api/client')
    vi.mocked(api).mockImplementation((path: string) => {
      if (path === '/catalog/redis') return Promise.resolve({
        slug: 'redis', name: 'Redis', default_cpu: 1, default_ram_mb: 1024,
        default_disk_gb: 4, installable: true, raw: { install_script: 'msg_ok done' },
      })
      if (path === '/hosts') return Promise.resolve(DEFAULT_HOSTS)
      if (path === '/storage') return Promise.reject(new Error('403'))
      return Promise.resolve(null)
    })
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={qc}>
        <InstallDialog slug="redis" onClose={vi.fn()} />
      </QueryClientProvider>,
    )
    await waitFor(() => expect(screen.getByRole('combobox', { name: /host/i })).toBeInTheDocument())
    await selectHost('host-01')
    fireEvent.change(screen.getByPlaceholderText('App name'), { target: { value: 'redis-1' } })
    fireEvent.click(screen.getByRole('checkbox', { name: /runs as root/i }))

    await screen.findByText(/could not read the storage pools/i)
    expect(screen.getByRole('button', { name: 'Install' })).toBeDisabled()
  })

  it('stops asking for consent once the host has already acknowledged', async () => {
    // Task 6's whole point: re-asking a host that already acknowledged
    // surfaces no new information.
    await mockStorage(DEFAULT_STORAGE,
      [{ id: 1, name: 'host-01', node_name: 'pve', install_consent_at: '2026-08-01T00:00:00Z' }])
    renderDialog()
    await waitFor(() => expect(screen.getByRole('combobox', { name: /host/i })).toBeInTheDocument())
    await selectHost('host-01')
    fireEvent.change(screen.getByPlaceholderText('App name'), { target: { value: 'redis-1' } })

    await waitFor(() =>
      expect(screen.queryByRole('checkbox', { name: /runs as root/i })).not.toBeInTheDocument())
    expect(screen.getByRole('button', { name: 'Install' })).toBeEnabled()
  })
})

describe('knownPool', () => {
  it('returns the remembered value when it is still a candidate', () => {
    expect(knownPool('lvm-a', ['lvm-a', 'lvm-b'])).toBe('lvm-a')
  })

  it('returns null for a remembered value that dropped out of candidates, even with one left', () => {
    // resolve_storage_pools never quietly swaps a remembered pool for the
    // sole survivor; it re-asks. `knownPool('lvm-gone', ['lvm-b'])` used to
    // return 'lvm-b', indistinguishable from the no-memory case.
    expect(knownPool('lvm-gone', ['lvm-b'])).toBeNull()
  })

  it('returns the sole candidate when nothing is remembered', () => {
    expect(knownPool(null, ['lvm-b'])).toBe('lvm-b')
  })

  it('returns null with no memory and more than one candidate', () => {
    expect(knownPool(null, ['lvm-a', 'lvm-b'])).toBeNull()
  })

  // pools.ts carries a `state` alongside the lists precisely because an empty
  // list is indistinguishable from "this host has no storage" until the
  // snapshot has been read. StorageFields destructured it away, so during the
  // fetch the Advanced block showed two pickers offering nothing, directly
  // under InstallDialog's own notice saying the pools were still being read.
  it('does not offer empty pool pickers while the pools are still being read', async () => {
    const { api } = await import('../api/client')
    const real = vi.mocked(api).getMockImplementation()!
    let release: () => void = () => {}
    const gate = new Promise<void>((r) => { release = r })
    vi.mocked(api).mockImplementation((path: string, opts?: RequestInit) =>
      path === '/storage' ? gate.then(() => real(path, opts)) as never : real(path, opts) as never)

    renderDialog()
    await openAdvanced()

    // No control at all beats a control that offers nothing: an empty picker
    // reads as a host with no pools, which is a different and wrong answer.
    expect(screen.queryByLabelText('Container storage')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Template storage')).not.toBeInTheDocument()

    release()
    vi.mocked(api).mockImplementation(real as never)
    await waitFor(() => expect(screen.getByLabelText('Container storage')).toBeInTheDocument())
    expect(optionsOf('Container storage')).toContain('local-lvm')
  })
})
