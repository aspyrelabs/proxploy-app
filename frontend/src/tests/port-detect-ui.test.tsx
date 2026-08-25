/**
 * Detecting a port for an adopted app, and saying out loud that it is a guess.
 *
 * An app from the store carries its port in the catalog. One adopted by hand
 * carries nothing, so the field is empty, so the row has no Open button.
 * Proxmox cannot answer it (no API route reports listening sockets), so the
 * only source is inside the container, and what comes back is ranked
 * heuristics rather than fact. The UI has to say so where the numbers are.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const calls: string[] = []
let ports: { port: number; process: string | null; address: string }[] = []

vi.mock('../api/client', () => ({
  ApiError: class extends Error {},
  apiErrorDetail: (_e: unknown, d: string) => d,
  inputCls: '',
  api: vi.fn((path: string) => {
    calls.push(path)
    if (path.endsWith('/ports')) return Promise.resolve({ ports, accurate: false })
    return Promise.resolve({})
  }),
}))
vi.mock('./LoginForm', () => ({ inputCls: '' }))

import { ReconfigureDialog } from '../components/ReconfigureDialog'

const APP = { id: 7, host_id: 1, ctid: 950, name: 'Proxploy-Test', status: 'running',
              web_port: null, web_protocol: null, web_path: '/' } as never

const wrap = () => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false },
                                                 mutations: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <ReconfigureDialog app={APP} onClose={() => {}} />
    </QueryClientProvider>)
}

beforeEach(() => {
  calls.length = 0
  ports = [{ port: 443, process: 'caddy', address: '*' },
           { port: 80, process: 'caddy', address: '*' }]
})

describe('detecting a port', () => {
  it('offers what the container was listening on, best first', async () => {
    wrap()
    fireEvent.click(screen.getByRole('button', { name: 'Detect' }))
    await waitFor(() => expect(calls).toContain('/apps/7/ports'))
    const found = await screen.findByRole('button', { name: /443/ })
    expect(found).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /80/ })).toBeInTheDocument()
  })

  it('says it is a guess, next to the numbers', async () => {
    // The whole caveat requirement: not a tooltip, not a doc, right there.
    wrap()
    fireEvent.click(screen.getByRole('button', { name: 'Detect' }))
    expect(await screen.findByText(/a guess, not a reading from proxmox/i))
      .toBeInTheDocument()
  })

  it('fills the field but never saves on its own', async () => {
    // A guess has to pass through the operator before it becomes the app's
    // port, so Detect writes the input and nothing else.
    wrap()
    fireEvent.click(screen.getByRole('button', { name: 'Detect' }))
    fireEvent.click(await screen.findByRole('button', { name: /443/ }))
    expect((screen.getByLabelText('Web port') as HTMLInputElement).value).toBe('443')
    expect(calls.filter((c) => c === '/apps/7')).toHaveLength(0)
  })

  it('says so plainly when nothing reachable is listening', async () => {
    ports = []
    wrap()
    fireEvent.click(screen.getByRole('button', { name: 'Detect' }))
    expect(await screen.findByText(/nothing was listening/i)).toBeInTheDocument()
  })
})
