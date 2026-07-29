import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { HostForm } from '../components/HostForm'

vi.mock('@tanstack/react-router', () => ({ useNavigate: () => vi.fn() }))

describe('HostForm', () => {
  it('shows the honest root-consent copy with the SSH checkbox', () => {
    render(<HostForm onCreated={() => {}} />)
    expect(screen.getByLabelText(/address/i)).toBeDefined()
    expect(screen.getByLabelText(/token id/i)).toBeDefined()
    expect(screen.getByText(/root shell on the node/i)).toBeDefined()
    expect(screen.getByRole('button', { name: /test connection/i })).toBeDefined()
  })
})
