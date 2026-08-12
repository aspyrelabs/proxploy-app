/** Toasts are the only in-app notification surface, so they carry their own
 *  controls: an x on each, and one way to clear the lot. */
import { render, screen, act, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { Toaster, toast } from 'sonner'
import { ClearAllToasts } from '../components/ClearAllToasts'

const wrap = () => render(<><Toaster closeButton /><ClearAllToasts /></>)

afterEach(() => act(() => { toast.dismiss() }))

describe('toast controls', () => {
  it('offers no clear-all when nothing is showing', () => {
    wrap()
    expect(screen.queryByRole('button', { name: /clear all/i })).not.toBeInTheDocument()
  })

  // One toast already has its own x. A "clear all" beside a single item is
  // two controls for one action.
  it('offers no clear-all for a single toast', async () => {
    wrap()
    act(() => { toast('one') })
    expect(await screen.findByText('one')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /clear all/i })).not.toBeInTheDocument()
  })

  it('offers clear-all once a second toast arrives', async () => {
    wrap()
    act(() => { toast('one'); toast('two') })
    expect(await screen.findByRole('button', { name: /clear all/i })).toBeInTheDocument()
  })

  it('clears every toast when pressed', async () => {
    const { getByRole } = wrap()
    act(() => { toast('one'); toast('two') })
    await screen.findByRole('button', { name: /clear all/i })
    act(() => { getByRole('button', { name: /clear all/i }).click() })
    // sonner keeps a dismissed toast mounted for its 200ms exit animation
    // (TIME_BEFORE_UNMOUNT in node_modules/sonner/dist/index.mjs) before
    // removing it from the DOM, so the assertion has to wait rather than
    // check synchronously right after the click.
    await waitFor(() => {
      expect(screen.queryByText('one')).not.toBeInTheDocument()
      expect(screen.queryByText('two')).not.toBeInTheDocument()
    })
  })
})
