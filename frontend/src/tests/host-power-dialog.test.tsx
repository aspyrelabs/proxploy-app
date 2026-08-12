import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const { toastSuccess, toastError } = vi.hoisted(() => ({ toastSuccess: vi.fn(), toastError: vi.fn() }))
vi.mock('../lib/notify', () => ({
  notify: { success: toastSuccess, error: toastError, info: vi.fn(), warning: vi.fn() },
}))

const { ApiError } = vi.hoisted(() => ({
  ApiError: class extends Error {
    status: number; body: unknown
    constructor(status: number, body: unknown) { super(`API ${status}`); this.status = status; this.body = body }
  },
}))

let isSelf = false
let powerFails = false
const calls: { path: string; method?: string; body: unknown }[] = []

vi.mock('../api/client', () => ({
  ApiError,
  api: vi.fn((path: string, opts?: RequestInit) => {
    const body = opts?.body ? JSON.parse(String(opts.body)) : null
    calls.push({ path, method: opts?.method, body })
    if (path.endsWith('/status')) {
      return Promise.resolve({ is_self: isSelf })
    }
    if (path.endsWith('/power')) {
      if (powerFails) {
        return Promise.reject(new ApiError(502, { error: 'unreachable', detail: 'the node did not answer' }))
      }
      const kind = body?.command === 'shutdown' ? 'host.shutdown' : 'host.reboot'
      return Promise.resolve({
        job: { id: 42, kind, status: 'queued', target_type: 'host', target_id: 1 },
        is_self: isSelf,
      })
    }
    if (path === '/jobs/42/events') return Promise.resolve([])
    return Promise.resolve(null)
  }),
}))

import { HostPowerDialog } from '../components/HostPowerDialog'

const wrap = (command: 'reboot' | 'shutdown', onClose = vi.fn()) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <HostPowerDialog hostId={1} node="pve1" command={command} onClose={onClose} />
    </QueryClientProvider>)
  return onClose
}

describe('HostPowerDialog', () => {
  beforeEach(() => { isSelf = false; powerFails = false; calls.length = 0; toastSuccess.mockClear(); toastError.mockClear() })
  afterEach(() => vi.restoreAllMocks())

  it('names the node and the action in the dialog', async () => {
    wrap('reboot')
    expect(await screen.findByText(/reboot pve1/i)).toBeInTheDocument()
  })

  // The gate is the whole safety mechanism here (doc 08 §9 row 14), and
  // "close enough" typing must never pass it.
  it('keeps Confirm disabled on a near miss and sends nothing', async () => {
    wrap('reboot')
    const confirm = await screen.findByRole('button', { name: 'Confirm' })
    expect(confirm).toBeDisabled()

    fireEvent.change(screen.getByLabelText(/type pve1 to confirm/i), { target: { value: 'pve1 ' } })
    expect(confirm).toBeDisabled()
    fireEvent.click(confirm)
    expect(calls.some((c) => c.path.endsWith('/power'))).toBe(false)
  })

  it('enables Confirm only on an exact match, and sends the command once clicked', async () => {
    wrap('reboot')
    const confirm = await screen.findByRole('button', { name: 'Confirm' })
    fireEvent.change(screen.getByLabelText(/type pve1 to confirm/i), { target: { value: 'pve1' } })
    expect(confirm).toBeEnabled()
    fireEvent.click(confirm)
    await waitFor(() => expect(calls.some((c) => c.path.endsWith('/power'))).toBe(true))
    const call = calls.find((c) => c.path.endsWith('/power'))!
    expect(call.body).toEqual({ command: 'reboot', confirm: 'pve1' })
  })

  it('sends the shutdown command for Power off', async () => {
    wrap('shutdown')
    fireEvent.change(await screen.findByLabelText(/type pve1 to confirm/i), { target: { value: 'pve1' } })
    fireEvent.click(screen.getByRole('button', { name: 'Confirm' }))
    await waitFor(() => expect(calls.some((c) => c.path.endsWith('/power'))).toBe(true))
    const call = calls.find((c) => c.path.endsWith('/power'))!
    expect(call.body).toEqual({ command: 'shutdown', confirm: 'pve1' })
  })

  // Reboot/power off now runs as a job (backend/proxploy/api/hosts.py::
  // power_node), so the dialog follows InstallDialog/UninstallDialog's shape:
  // it holds the returned job id and mounts JobLog, rather than closing and
  // firing its own success toast. The job's own SSE event (LiveProvider)
  // raises the notification card, this dialog would otherwise double it.
  it('shows the job transcript rather than closing, once the action is sent', async () => {
    const onClose = wrap('reboot')
    fireEvent.change(await screen.findByLabelText(/type pve1 to confirm/i), { target: { value: 'pve1' } })
    fireEvent.click(screen.getByRole('button', { name: 'Confirm' }))
    await waitFor(() => expect(calls.some((c) => c.path === '/jobs/42/events')).toBe(true))
    expect(onClose).not.toHaveBeenCalled()
    expect(toastSuccess).not.toHaveBeenCalled()
  })

  it('the Close button in the job view still calls onClose', async () => {
    const onClose = wrap('reboot')
    fireEvent.change(await screen.findByLabelText(/type pve1 to confirm/i), { target: { value: 'pve1' } })
    fireEvent.click(screen.getByRole('button', { name: 'Confirm' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Close' }))
    expect(onClose).toHaveBeenCalled()
  })

  it('surfaces a failed power call rather than pretending it worked', async () => {
    powerFails = true
    wrap('reboot')
    fireEvent.change(await screen.findByLabelText(/type pve1 to confirm/i), { target: { value: 'pve1' } })
    fireEvent.click(screen.getByRole('button', { name: 'Confirm' }))
    await waitFor(() => expect(toastError).toHaveBeenCalled())
  })

  // The whole point of doc 02 §9 / doc 08 §1: an operator must never be
  // surprised by this. The warning has to be visible BEFORE Confirm is even
  // reachable, not discovered only after the node goes down.
  it('names this as Proxploy\'s own node and states the cost, when it is self', async () => {
    isSelf = true
    wrap('shutdown')
    expect(await screen.findByText(/proxploy itself runs on/i)).toBeInTheDocument()
    expect(screen.getByText(/physical or ipmi/i)).toBeInTheDocument()
  })

  it('does not show the self warning for an ordinary node', async () => {
    isSelf = false
    wrap('reboot')
    // Wait for the status query to settle before asserting an absence, or
    // this would pass trivially before the (non-existent) warning had any
    // chance to render.
    await screen.findByText(/cannot be undone/i)
    expect(screen.queryByText(/proxploy itself runs on/i)).not.toBeInTheDocument()
  })

  it('still lets a confirmed self action through -- the gate is a backstop, not a refusal', async () => {
    isSelf = true
    wrap('shutdown')
    fireEvent.change(await screen.findByLabelText(/type pve1 to confirm/i), { target: { value: 'pve1' } })
    fireEvent.click(screen.getByRole('button', { name: 'Confirm' }))
    await waitFor(() => expect(calls.some((c) => c.path.endsWith('/power'))).toBe(true))
    const call = calls.find((c) => c.path.endsWith('/power'))!
    expect(call.body).toEqual({ command: 'shutdown', confirm: 'pve1' })
    await waitFor(() => expect(calls.some((c) => c.path === '/jobs/42/events')).toBe(true))
  })
})
