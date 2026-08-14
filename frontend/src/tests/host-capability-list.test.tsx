import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const { ApiError } = vi.hoisted(() => ({
  ApiError: class extends Error {
    status: number; body: unknown
    constructor(status: number, body: unknown) { super(`API ${status}`); this.status = status; this.body = body }
  },
}))

const calls: { path: string; body: any }[] = []
let capabilities: Record<string, boolean> = {
  monitoring: true, lifecycle: false, console: false, backup: false,
}
let reject = false

vi.mock('../api/client', () => ({
  ApiError,
  api: vi.fn((path: string, opts?: RequestInit) => {
    const body = opts?.body ? JSON.parse(String(opts.body)) : null
    calls.push({ path, body })
    if (path.endsWith('/credentials')) {
      if (reject) {
        return Promise.reject(new ApiError(502, {
          error: 'token_rejected',
          detail: 'the new token did not work against https://10.0.0.9:8006, '
                + 'the old one is still in place: auth failed',
        }))
      }
      return Promise.resolve({ id: 3, rotated: [`api_token:${body.capability}`] })
    }
    return Promise.resolve({ id: 3, name: 'pve-01', capabilities })
  }),
}))

import { HostCapabilityList } from '../components/HostCapabilityList'

const wrap = () => {
  const qc = new QueryClient({ defaultOptions: {
    queries: { retry: false }, mutations: { retry: false } } })
  const view = render(<QueryClientProvider client={qc}>
    <HostCapabilityList hostId={3} />
  </QueryClientProvider>)
  return { ...view, qc }
}

describe('HostCapabilityList', () => {
  beforeEach(() => {
    calls.length = 0; reject = false
    capabilities = { monitoring: true, lifecycle: false, console: false, backup: false }
  })
  afterEach(() => vi.restoreAllMocks())

  it('lists every capability, stored and missing alike', async () => {
    wrap()
    expect(await screen.findByText('Monitoring')).toBeInTheDocument()
    for (const label of ['Lifecycle', 'Console', 'Backup']) {
      expect(screen.getByText(label)).toBeInTheDocument()
    }
  })

  it('renders a capability the backend added without a second list here', async () => {
    capabilities = { ...capabilities, teleportation: false }
    wrap()
    expect(await screen.findByText('Teleportation')).toBeInTheDocument()
  })

  it('offers monitoring as rotate-only, never missing or removable', async () => {
    wrap()
    await screen.findByText('Monitoring')
    expect(screen.getByRole('button', { name: 'Rotate Monitoring token, show fields' }))
      .toBeEnabled()
    expect(screen.queryByRole('button', { name: /remove monitoring/i })).not.toBeInTheDocument()
    // Its fields are behind the rotate control, not open as an unfilled gap.
    expect(screen.queryByLabelText('Monitoring token id')).not.toBeInTheDocument()
  })

  it('shows a missing capability as an open field, and stores it with its own key', async () => {
    wrap()
    await screen.findByText('Lifecycle')
    fireEvent.change(screen.getByLabelText('Lifecycle token id'),
                     { target: { value: 'proxploy@pve!lifecycle' } })
    fireEvent.change(screen.getByLabelText('Lifecycle token secret'),
                     { target: { value: 'lc' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add Lifecycle token' }))

    await waitFor(() => expect(calls.at(-1)).toEqual({
      path: '/hosts/3/credentials',
      body: { token_id: 'proxploy@pve!lifecycle', token_secret: 'lc',
              capability: 'lifecycle' },
    }))
  })

  it('names the capability when the node rejects its token', async () => {
    reject = true
    wrap()
    await screen.findByText('Backup')
    fireEvent.change(screen.getByLabelText('Backup token id'), { target: { value: 'x' } })
    fireEvent.change(screen.getByLabelText('Backup token secret'), { target: { value: 'y' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add Backup token' }))
    expect(await screen.findByText(/Backup: .*did not work/i)).toBeInTheDocument()
  })

  it('never submits half a token pair', async () => {
    wrap()
    await screen.findByText('Console')
    fireEvent.change(screen.getByLabelText('Console token id'), { target: { value: 'only-id' } })
    const btn = screen.getByRole('button', { name: 'Add Console token' })
    expect(btn).toBeDisabled()
    // Finding #11: clicking a disabled button can't fire onClick, so
    // asserting no call followed made that half of this test tautological.
    // Assert the actual warning copy instead.
    expect(screen.getByText('Token id and secret must both be filled in.')).toBeInTheDocument()
  })

  // Finding #5: the onSuccess handler deliberately deviates from the plan's
  // prefix invalidate -- it patches ['hosts', hostId] directly and
  // invalidates ['hosts'] with exact: true. Neither half was tested.
  it('flips the row to stored and closes its fields on a successful Add', async () => {
    wrap()
    await screen.findByText('Lifecycle')
    fireEvent.change(screen.getByLabelText('Lifecycle token id'),
                     { target: { value: 'proxploy@pve!lifecycle' } })
    fireEvent.change(screen.getByLabelText('Lifecycle token secret'),
                     { target: { value: 'lc' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add Lifecycle token' }))

    const row = (await screen.findByText('Lifecycle')).closest('.border-t') as HTMLElement
    await waitFor(() => expect(
      within(row).getByRole('button', { name: 'Lifecycle token already stored' }),
    ).toBeDisabled())
    expect(within(row).queryByLabelText('Lifecycle token id')).not.toBeInTheDocument()
  })

  it('patches the cached host detail in place, preserving its other fields, and invalidates the hosts list by exact key', async () => {
    const { qc } = wrap()
    const invalidateSpy = vi.spyOn(qc, 'invalidateQueries')
    await screen.findByText('Lifecycle')
    fireEvent.change(screen.getByLabelText('Lifecycle token id'),
                     { target: { value: 'proxploy@pve!lifecycle' } })
    fireEvent.change(screen.getByLabelText('Lifecycle token secret'),
                     { target: { value: 'lc' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add Lifecycle token' }))

    await waitFor(() => expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['hosts'], exact: true }))
    const cached = qc.getQueryData<{ id: number; name: string; capabilities: Record<string, boolean> }>(
      ['hosts', 3])
    // The fields that were already in the cache (id, name) survive the
    // patch -- it's a merge, not a replacement.
    expect(cached?.id).toBe(3)
    expect(cached?.name).toBe('pve-01')
    expect(cached?.capabilities).toEqual({
      monitoring: true, lifecycle: true, console: false, backup: false,
    })
  })

  // The Add/Rotate pair. Exactly one of the two is live per row, and which
  // one is the only thing that reports whether the capability has a token,
  // now that the separate "stored" / "not configured" text is gone.
  describe('the Add and Rotate group', () => {
    const rowOf = (label: string) =>
      screen.getByText(label).closest('.border-t') as HTMLElement

    it('gives every capability its own group, not just the configured ones', async () => {
      wrap()
      await screen.findByText('Monitoring')
      for (const label of ['Monitoring', 'Lifecycle', 'Console', 'Backup']) {
        const group = within(rowOf(label)).getByRole('group')
        expect(within(group).getAllByRole('button')).toHaveLength(2)
      }
    })

    it('reads Stored in green and offers Rotate when a token is already held', async () => {
      wrap()
      await screen.findByText('Monitoring')
      const group = within(rowOf('Monitoring')).getByRole('group')

      const stored = within(group).getByRole('button', { name: 'Monitoring token already stored' })
      expect(stored).toHaveTextContent('Stored')
      expect(stored).toBeDisabled()
      // The same green the status text used before the button absorbed it,
      // and undimmed, since it is a readout rather than a withheld control.
      // `text-green!`, not `text-green`. jsdom applies no stylesheet, so this
      // cannot assert the rendered colour; what it CAN pin is the important
      // modifier, whose absence let ghost's `text-text` win on stylesheet
      // order and render Stored the same near-white as Add, with the plain
      // class present and this assertion passing. Verified green in a real
      // browser separately.
      expect(stored).toHaveClass('text-green!')
      expect(stored.className).not.toMatch(/(^|\s)text-green(\s|$)/)
      expect(stored).toHaveClass('disabled:opacity-100')

      expect(within(group).getByRole('button', { name: /^Rotate Monitoring token/ })).toBeEnabled()
    })

    it('offers Add, and refuses Rotate, while a capability has no token', async () => {
      wrap()
      await screen.findByText('Backup')
      const group = within(rowOf('Backup')).getByRole('group')

      const add = within(group).getByRole('button', { name: 'Add Backup token, show fields' })
      expect(add).toHaveTextContent('Add')
      expect(add).toBeEnabled()
      // Nothing to rotate, so the control says so rather than opening the
      // very fields Add opens and leaving the operator to guess.
      expect(within(group).getByRole('button', { name: /^Rotate Backup token/ })).toBeDisabled()
    })

    it('puts the caret in the token id field when Add is pressed on an open row', async () => {
      wrap()
      await screen.findByText('Console')
      // The row is already open (the gap is the prompt), so this click is the
      // one that would otherwise appear to do nothing.
      fireEvent.click(screen.getByRole('button', { name: 'Add Console token, show fields' }))
      expect(screen.getByLabelText('Console token id')).toHaveFocus()
    })

    it('opens the fields from Rotate on a stored capability', async () => {
      wrap()
      await screen.findByText('Monitoring')
      expect(screen.queryByLabelText('Monitoring token id')).not.toBeInTheDocument()
      fireEvent.click(screen.getByRole('button', { name: 'Rotate Monitoring token, show fields' }))
      expect(screen.getByLabelText('Monitoring token id')).toBeInTheDocument()
      // The submit that appears is the row's other Rotate, and it is named
      // apart from the group's so neither is ambiguous while both are on screen.
      expect(screen.getByRole('button', { name: 'Rotate Monitoring token' })).toBeInTheDocument()
    })
  })
})
