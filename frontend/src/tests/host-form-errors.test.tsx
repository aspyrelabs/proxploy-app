import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { api, ApiError } from '../api/client'
import { HostForm } from '../components/HostForm'

vi.mock('../api/client', async (orig) => ({
  ...(await orig() as object),
  api: vi.fn(),
}))

describe('HostForm error copy', () => {
  it('tells a wrong token apart from an unreachable box', async () => {
    vi.mocked(api).mockRejectedValue(new ApiError(502, { error: 'auth', detail: '401' }))
    render(<HostForm onCreated={() => {}} />)
    fireEvent.click(screen.getByRole('button', { name: 'Test connection' }))
    expect(await screen.findByText(/rejected the api token/i)).toBeInTheDocument()
  })

  it('names a fingerprint mismatch as the security event it is', async () => {
    vi.mocked(api).mockRejectedValue(new ApiError(502, { error: 'tls_fingerprint', detail: 'x' }))
    render(<HostForm onCreated={() => {}} />)
    fireEvent.click(screen.getByRole('button', { name: 'Test connection' }))
    expect(await screen.findByText(/fingerprint/i)).toBeInTheDocument()
  })

  it('tells an unreachable box apart from a rejected token', async () => {
    vi.mocked(api).mockRejectedValue(new ApiError(502, { error: 'unreachable', detail: 'x' }))
    render(<HostForm onCreated={() => {}} />)
    fireEvent.click(screen.getByRole('button', { name: 'Test connection' }))
    expect(await screen.findByText(/reach/i)).toBeInTheDocument()
  })

  it('names an SSRF refusal instead of a generic failure', async () => {
    vi.mocked(api).mockRejectedValue(new ApiError(502, { error: 'refused', detail: 'x' }))
    render(<HostForm onCreated={() => {}} />)
    fireEvent.click(screen.getByRole('button', { name: 'Test connection' }))
    expect(await screen.findByText(/unsafe/i)).toBeInTheDocument()
  })

  it('names a duplicate host on 409', async () => {
    vi.mocked(api).mockRejectedValue(new ApiError(409, {}))
    render(<HostForm onCreated={() => {}} />)
    fireEvent.click(screen.getByRole('button', { name: 'Test connection' }))
    expect(await screen.findByText(/already exists/i)).toBeInTheDocument()
  })
})
