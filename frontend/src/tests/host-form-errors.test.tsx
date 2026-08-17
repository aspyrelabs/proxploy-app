import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { api, ApiError } from '../api/client'
import { HostForm } from '../components/HostForm'

vi.mock('../api/client', async (orig) => ({
  ...(await orig() as object),
  api: vi.fn(),
}))

const withQuery = (ui: React.ReactNode) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

describe('HostForm error copy', () => {
  it('tells a wrong token apart from an unreachable box', async () => {
    vi.mocked(api).mockRejectedValue(new ApiError(502, { error: 'auth', detail: '401' }))
    withQuery(<HostForm onCreated={() => {}} />)
    fireEvent.click(screen.getByRole('button', { name: 'Test connection' }))
    expect(await screen.findByText(/rejected the api token/i)).toBeInTheDocument()
  })

  it('names a fingerprint mismatch as the security event it is', async () => {
    vi.mocked(api).mockRejectedValue(new ApiError(502, { error: 'tls_fingerprint', detail: 'x' }))
    withQuery(<HostForm onCreated={() => {}} />)
    fireEvent.click(screen.getByRole('button', { name: 'Test connection' }))
    expect(await screen.findByText(/fingerprint/i)).toBeInTheDocument()
  })

  it('tells an unreachable box apart from a rejected token', async () => {
    vi.mocked(api).mockRejectedValue(new ApiError(502, { error: 'unreachable', detail: 'x' }))
    withQuery(<HostForm onCreated={() => {}} />)
    fireEvent.click(screen.getByRole('button', { name: 'Test connection' }))
    expect(await screen.findByText(/reach/i)).toBeInTheDocument()
  })

  it('names an SSRF refusal instead of a generic failure', async () => {
    vi.mocked(api).mockRejectedValue(new ApiError(502, { error: 'refused', detail: 'x' }))
    withQuery(<HostForm onCreated={() => {}} />)
    fireEvent.click(screen.getByRole('button', { name: 'Test connection' }))
    expect(await screen.findByText(/unsafe/i)).toBeInTheDocument()
  })

  it('names a duplicate host on 409', async () => {
    vi.mocked(api).mockRejectedValue(new ApiError(409, {}))
    withQuery(<HostForm onCreated={() => {}} />)
    fireEvent.click(screen.getByRole('button', { name: 'Test connection' }))
    expect(await screen.findByText(/already exists/i)).toBeInTheDocument()
  })

  // KIND_COPY says what to DO about a kind. The server's `detail` says what
  // actually happened, and only it can: which privilege Proxmox refused
  // (services/proxmox.py::_permission_detail), or which fingerprint was pinned
  // against which was presented. Showing only the advice threw the diagnosis
  // away, which is doc 11's carried "swallowed error detail".
  it('keeps the privilege Proxmox named, not just the advice', async () => {
    vi.mocked(api).mockRejectedValue(new ApiError(502, {
      error: 'permission',
      detail: 'version check failed: Sys.Console on /nodes/pve1' }))
    withQuery(<HostForm onCreated={() => {}} />)
    fireEvent.click(screen.getByRole('button', { name: 'Test connection' }))
    expect(await screen.findByText(/Sys\.Console on \/nodes\/pve1/)).toBeInTheDocument()
  })

  it('keeps both fingerprints on a mismatch, not just the word fingerprint', async () => {
    vi.mocked(api).mockRejectedValue(new ApiError(502, {
      error: 'tls_fingerprint',
      detail: 'TLS fingerprint mismatch: pinned 47:43:8A, got 29:F9:DA' }))
    withQuery(<HostForm onCreated={() => {}} />)
    fireEvent.click(screen.getByRole('button', { name: 'Test connection' }))
    expect(await screen.findByText(/pinned 47:43:8A, got 29:F9:DA/)).toBeInTheDocument()
  })

  it('still shows the advice alone when the server sent no detail', async () => {
    vi.mocked(api).mockRejectedValue(new ApiError(502, { error: 'auth' }))
    withQuery(<HostForm onCreated={() => {}} />)
    fireEvent.click(screen.getByRole('button', { name: 'Test connection' }))
    expect(await screen.findByText(/rejected the api token/i)).toBeInTheDocument()
  })
})
