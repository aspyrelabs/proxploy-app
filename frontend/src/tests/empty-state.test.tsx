import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { EmptyState } from '../components/EmptyState'

describe('EmptyState', () => {
  it('renders title and note with no action', () => {
    render(<EmptyState title="No hosts yet" note="Add one to get started." />)
    expect(screen.getByText('No hosts yet')).toBeInTheDocument()
    expect(screen.getByText('Add one to get started.')).toBeInTheDocument()
  })

  it('renders an action when given one', () => {
    render(<EmptyState title="No hosts yet" note="Add one."
                       action={<button>Add a host</button>} />)
    expect(screen.getByRole('button', { name: 'Add a host' })).toBeInTheDocument()
  })
})
