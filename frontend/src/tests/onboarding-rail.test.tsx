import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { OnboardingRail, type RailStep } from '../components/OnboardingRail'

const steps: RailStep[] = [
  { label: 'Admin account', status: 'done', detail: 'ops@acme.io', reachable: true },
  { label: 'First host', status: 'current', reachable: true },
  { label: 'Authorize installs', status: 'todo', reachable: false },
  { label: 'Done', status: 'todo', reachable: false },
]

describe('OnboardingRail', () => {
  it('marks the completed step done and the active step current', () => {
    render(<OnboardingRail steps={steps} view={1} onSelect={() => {}} />)
    expect(screen.getByRole('button', { name: /admin account/i })
      .getAttribute('data-status')).toBe('done')
    expect(screen.getByRole('button', { name: /first host/i })
      .getAttribute('aria-current')).toBe('step')
  })

  it('shows the summary detail on a completed step', () => {
    render(<OnboardingRail steps={steps} view={1} onSelect={() => {}} />)
    expect(screen.getByText('ops@acme.io')).toBeInTheDocument()
  })

  it('calls onSelect for a reachable step', () => {
    const onSelect = vi.fn()
    render(<OnboardingRail steps={steps} view={1} onSelect={onSelect} />)
    fireEvent.click(screen.getByRole('button', { name: /admin account/i }))
    expect(onSelect).toHaveBeenCalledWith(0)
  })

  it('does not call onSelect for an unreachable step', () => {
    const onSelect = vi.fn()
    render(<OnboardingRail steps={steps} view={1} onSelect={onSelect} />)
    fireEvent.click(screen.getByRole('button', { name: /authorize installs/i }))
    expect(onSelect).not.toHaveBeenCalled()
  })

  it('renders a skipped step as skipped and still reachable', () => {
    const skipped: RailStep[] = [
      ...steps.slice(0, 1),
      { label: 'First host', status: 'skipped', detail: 'Skipped', reachable: true },
      ...steps.slice(2),
    ]
    const onSelect = vi.fn()
    render(<OnboardingRail steps={skipped} view={3} onSelect={onSelect} />)
    const host = screen.getByRole('button', { name: /first host/i })
    expect(host.getAttribute('data-status')).toBe('skipped')
    fireEvent.click(host)
    expect(onSelect).toHaveBeenCalledWith(1)
  })
})
