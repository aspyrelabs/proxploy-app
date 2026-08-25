/**
 * A guest being acted on says so, and does not claim a settled status.
 *
 * Reported on hardware 2026-08-25: stopping anytype-server showed Working,
 * then Running again, then Stopped. The flap itself is the poller's, fixed in
 * pollers/__init__.py; this is the other half, which is that the in-between
 * state has to LOOK unfinished rather than like one more settled answer in the
 * same shape as Running and Stopped.
 */
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { StatusPill } from '../components/StatusPill'

describe('StatusPill', () => {
  it('spins and says Working while an action is in flight', () => {
    const { container } = render(<StatusPill status="pending" />)
    expect(screen.getByText('Working')).toBeInTheDocument()
    // Not "Pending", which is what a queue is.
    expect(screen.queryByText(/pending/i)).toBeNull()
    expect(container.querySelector('[data-slot="spinner"]')).not.toBeNull()
  })

  it('shows a still dot for every settled status', () => {
    for (const s of ['running', 'stopped', 'paused', 'unknown']) {
      const { container, unmount } = render(<StatusPill status={s} />)
      expect(container.querySelector('[data-slot="spinner"]')).toBeNull()
      unmount()
    }
  })

  it('spins and says Removing while an app is being uninstalled', () => {
    // Its own word and its own colour: a removal ends with the row gone, so it
    // is not the same news as a stop.
    const { container } = render(<StatusPill status="removing" />)
    expect(screen.getByText('Removing')).toBeInTheDocument()
    expect(container.querySelector('[data-slot="spinner"]')).not.toBeNull()
    expect(container.firstElementChild?.className).toContain('text-red')
  })

  it('hides the spinner from a screen reader, since the label already says it', () => {
    const { container } = render(<StatusPill status="pending" />)
    expect(container.querySelector('[data-slot="spinner"]'))
      .toHaveAttribute('aria-hidden', 'true')
  })
})
