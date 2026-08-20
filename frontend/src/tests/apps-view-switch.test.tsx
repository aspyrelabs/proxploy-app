import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

vi.mock('../components/ui/icon', () => ({
  Icon: ({ name }: { name: string }) => <span data-icon={name} />,
}))

import { AppsViewSwitch } from '../components/AppsViewSwitch'

describe('AppsViewSwitch', () => {
  it('names each view, so the icon-only buttons are reachable without sight', () => {
    render(<AppsViewSwitch value="detailed" onChange={() => {}} />)
    expect(screen.getByRole('button', { name: 'Detailed view' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'List view' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Icon view' })).toBeInTheDocument()
  })

  it('marks the current view pressed rather than only styling it', () => {
    render(<AppsViewSwitch value="list" onChange={() => {}} />)
    expect(screen.getByRole('button', { name: 'List view' }))
      .toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: 'Icon view' }))
      .toHaveAttribute('aria-pressed', 'false')
  })

  it('reports the chosen view', () => {
    // fireEvent, not user-event: @testing-library/user-event is not a
    // dependency of this repo and every existing suite drives clicks this way.
    const onChange = vi.fn()
    render(<AppsViewSwitch value="detailed" onChange={onChange} />)
    fireEvent.click(screen.getByRole('button', { name: 'Icon view' }))
    expect(onChange).toHaveBeenCalledWith('icon')
  })
})
