import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

const calls: { path: string; method: string; body: any }[] = []

let stores: any[] = [
  { host_id: 1, storage: 'local', type: 'dir', content: ['backup', 'iso'] },
  { host_id: 1, storage: 'local-lvm', type: 'lvmthin', content: ['rootdir', 'images'] },
]

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
      if (method !== 'GET') calls.push({ path, method, body })
      if (path === '/hosts') return Promise.resolve([{ id: 1, name: 'host-01', cluster_name: null }])
      if (path === '/storage') return Promise.resolve(stores)
      if (path === '/backups/run') {
        return Promise.resolve({ job: { id: 41, kind: 'backup.run', status: 'queued' } })
      }
      return Promise.resolve(null)
    }),
  }
})

import { BackupGuestDialog, type BackupGuestTarget } from '../components/BackupGuestDialog'

const APP: BackupGuestTarget = {
  type: 'app', id: 7, name: 'Immich', hostId: 1, hostName: 'host-01', label: 'CT 150',
}
const VM: BackupGuestTarget = {
  type: 'vm', id: 3, name: 'win-build', hostId: 1, hostName: 'host-01', label: 'VM 100',
}

const wrap = (guest: BackupGuestTarget) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <BackupGuestDialog guest={guest} onClose={() => {}} />
    </QueryClientProvider>,
  )
}

describe('BackupGuestDialog', () => {
  it('runs a backup of just this app, sending the guest and the chosen storage', async () => {
    calls.length = 0
    wrap(APP)
    await waitFor(() => expect(screen.getByRole('button', { name: 'Start backup' })).toBeEnabled())
    // Only the store that carries `backup` content is on offer, same rule
    // RunDialog enforces host-wide.
    const target = screen.getByLabelText(/archive lands on/i)
    expect(target).toHaveValue('local')
    expect(screen.getByText(/CT 150/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Start backup' }))
    await waitFor(() => expect(calls.length).toBe(1))
    expect(calls[0].path).toBe('/backups/run')
    expect(calls[0].body).toEqual({
      guests: [{ type: 'app', id: 7 }], host_id: 1, storage: 'local',
    })
    expect(await screen.findByRole('button', { name: 'Close' })).toBeInTheDocument()
  })

  it('runs the same one-guest backup for a VM, sending type vm', async () => {
    calls.length = 0
    stores = [
      { host_id: 1, storage: 'local', type: 'dir', content: ['backup', 'iso'] },
      { host_id: 1, storage: 'local-lvm', type: 'lvmthin', content: ['rootdir', 'images'] },
    ]
    wrap(VM)
    await waitFor(() => expect(screen.getByRole('button', { name: 'Start backup' })).toBeEnabled())
    // The VM's own identity line and noun, not the app wording.
    expect(screen.getByText(/VM 100/)).toBeInTheDocument()
    expect(screen.getByText(/virtual machine keeps running/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Start backup' }))
    await waitFor(() => expect(calls.length).toBe(1))
    expect(calls[0].body).toEqual({
      guests: [{ type: 'vm', id: 3 }], host_id: 1, storage: 'local',
    })
  })

  it('blocks with a plain explanation when no storage on the host accepts backups', async () => {
    calls.length = 0
    stores = [{ host_id: 1, storage: 'local-lvm', type: 'lvmthin', content: ['rootdir'] }]
    wrap(APP)
    expect(await screen.findByText(/No storage on host-01 accepts backups/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Start backup' })).toBeDisabled()
  })
})
