import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

const ALIASES = { aliases: [
  { name: 'office', cidr: '10.0.0.0/24', comment: 'the office range', digest: 'd1' },
] }
const IPSETS = { ipsets: [{ name: 'trusted', comment: 'known hosts', digest: 'd1' }] }
const MEMBERS = { members: [
  { cidr: '10.0.0.5', comment: 'the jump box' },
  { cidr: '10.0.0.99', nomatch: 1, comment: 'except this one' },
] }
const GROUPS = { groups: [{ group: 'web', comment: 'public services' }] }

const calls: { path: string; method: string; body: any }[] = []

/** Path suffixes the fake api should reject instead of answering, set by the
 *  failed-read cases at the bottom of each block. */
let failing: string | null = null

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return {
    ...actual,
    api: vi.fn((path: string, opts?: RequestInit) => {
      const method = (opts?.method ?? 'GET').toUpperCase()
      if (method !== 'GET') {
        calls.push({ path, method, body: opts?.body ? JSON.parse(String(opts.body)) : {} })
        return Promise.resolve({ ok: true })
      }
      if (failing && path.endsWith(failing)) {
        return Promise.reject(new actual.ApiError(502, { detail: 'Proxmox refused the request' }))
      }
      if (path.endsWith('/members')) return Promise.resolve(MEMBERS)
      if (path.endsWith('/aliases')) return Promise.resolve(ALIASES)
      if (path.endsWith('/ipsets')) return Promise.resolve(IPSETS)
      if (path.endsWith('/groups')) return Promise.resolve(GROUPS)
      return Promise.resolve({})
    }),
  }
})

import { AliasTable, IpSetPanel, SecurityGroupList } from '../components/FirewallObjects'

const SCOPE = { kind: 'cluster', hostId: 1 } as const

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

describe('AliasTable', () => {
  it('lists aliases with the range each one stands for', async () => {
    wrap(<AliasTable scope={SCOPE} canEdit />)
    await screen.findByText('office')
    expect(screen.getByText('10.0.0.0/24')).toBeTruthy()
    expect(screen.getByText('the office range')).toBeTruthy()
  })

  it('creates an alias', async () => {
    calls.length = 0
    wrap(<AliasTable scope={SCOPE} canEdit />)
    await screen.findByText('office')
    fireEvent.click(screen.getByRole('button', { name: /add alias/i }))
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'dmz' } })
    fireEvent.change(screen.getByLabelText('Address or range'),
      { target: { value: '10.9.0.0/24' } })
    fireEvent.click(screen.getByRole('button', { name: /^save alias$/i }))
    await waitFor(() => expect(calls).toHaveLength(1))
    expect(calls[0].path).toBe('/firewall/cluster/1/aliases')
    expect(calls[0].body).toEqual({ name: 'dmz', cidr: '10.9.0.0/24' })
  })

  it('is read only for a viewer', async () => {
    wrap(<AliasTable scope={SCOPE} canEdit={false} />)
    await screen.findByText('office')
    expect(screen.queryByRole('button', { name: /add alias/i })).toBeNull()
  })

  it('says the read failed rather than that there are no aliases', async () => {
    failing = '/aliases'
    try {
      wrap(<AliasTable scope={SCOPE} canEdit />)
      await screen.findByText(/could not read these aliases/i)
      expect(screen.queryByText(/no aliases here yet/i)).toBeNull()
    } finally {
      failing = null
    }
  })
})

describe('IpSetPanel', () => {
  it('shows a set and its members once the set is opened', async () => {
    wrap(<IpSetPanel scope={SCOPE} canEdit />)
    await screen.findByText('trusted')
    fireEvent.click(screen.getByRole('button', { name: /open IP set trusted/i }))
    await screen.findByText('10.0.0.5')
  })

  it('marks a nomatch member as an exclusion, not as an ordinary entry', async () => {
    // nomatch inverts the member: the set matches everything in it EXCEPT
    // this. Rendering it like the others would state the opposite of the truth.
    wrap(<IpSetPanel scope={SCOPE} canEdit />)
    await screen.findByText('trusted')
    fireEvent.click(screen.getByRole('button', { name: /open IP set trusted/i }))
    await screen.findByText('10.0.0.99')
    expect(screen.getByLabelText('10.0.0.99 is excluded from this set')).toBeTruthy()
  })

  it('escapes the slash when deleting a member', async () => {
    // The CIDR is a path segment on both hops. Unescaped, the request never
    // reaches the handler.
    calls.length = 0
    wrap(<IpSetPanel scope={SCOPE} canEdit />)
    await screen.findByText('trusted')
    fireEvent.click(screen.getByRole('button', { name: /open IP set trusted/i }))
    await screen.findByText('10.0.0.5')
    fireEvent.click(screen.getByLabelText('Remove 10.0.0.5 from trusted'))
    await waitFor(() => expect(calls).toHaveLength(1))
    expect(calls[0].path).toBe('/firewall/cluster/1/ipsets/trusted/members/10.0.0.5')
  })

  it('asks before dropping a set that still has members in it', async () => {
    calls.length = 0
    wrap(<IpSetPanel scope={SCOPE} canEdit />)
    await screen.findByText('trusted')
    fireEvent.click(screen.getByRole('button', { name: /open IP set trusted/i }))
    await screen.findByText('10.0.0.5')
    fireEvent.click(screen.getByLabelText('Delete IP set trusted'))
    // Nothing sent yet: the confirmation is the point, since force discards
    // members the operator may not have looked at.
    expect(calls).toHaveLength(0)
    await screen.findByText(/2 addresses/i)
    fireEvent.click(screen.getByRole('button', { name: /delete it and its members/i }))
    await waitFor(() => expect(calls).toHaveLength(1))
    expect(calls[0].path).toContain('force=true')
  })

  it('says the read failed rather than that there are no IP sets', async () => {
    failing = '/ipsets'
    try {
      wrap(<IpSetPanel scope={SCOPE} canEdit />)
      await screen.findByText(/could not read these IP sets/i)
      expect(screen.queryByText(/no IP sets here yet/i)).toBeNull()
    } finally {
      failing = null
    }
  })

  it('will not say a set holds 0 addresses when it could not read the set', async () => {
    // "Holds 0 addresses. Deleting it removes them too." reads as a safe
    // delete. On a failed read nobody knows what is about to go.
    wrap(<IpSetPanel scope={SCOPE} canEdit />)
    await screen.findByText('trusted')
    failing = '/members'
    try {
      fireEvent.click(screen.getByLabelText('Delete IP set trusted'))
      await screen.findByText(/could not read what is in this set/i)
      expect(screen.queryByText(/0 addresses/i)).toBeNull()
    } finally {
      failing = null
    }
  })
})

describe('SecurityGroupList', () => {
  it('lists groups and selects one', async () => {
    const picked: (string | null)[] = []
    wrap(<SecurityGroupList hostId={1} canEdit selected={null}
      onSelect={g => picked.push(g)} />)
    await screen.findByText('web')
    fireEvent.click(screen.getByRole('button', { name: /open security group web/i }))
    expect(picked).toEqual(['web'])
  })

  it('creates a group', async () => {
    calls.length = 0
    wrap(<SecurityGroupList hostId={1} canEdit selected={null} onSelect={() => {}} />)
    await screen.findByText('web')
    fireEvent.click(screen.getByRole('button', { name: /add group/i }))
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'db' } })
    fireEvent.click(screen.getByRole('button', { name: /^save group$/i }))
    await waitFor(() => expect(calls).toHaveLength(1))
    expect(calls[0].body).toEqual({ group: 'db' })
  })

  it('says the read failed rather than that there are no security groups', async () => {
    failing = '/groups'
    try {
      wrap(<SecurityGroupList hostId={1} canEdit selected={null} onSelect={() => {}} />)
      await screen.findByText(/could not read these security groups/i)
      expect(screen.queryByText(/no security groups here yet/i)).toBeNull()
    } finally {
      failing = null
    }
  })
})
