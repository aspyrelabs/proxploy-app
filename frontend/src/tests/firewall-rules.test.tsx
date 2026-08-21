import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

const RULES = {
  scope: 'cluster',
  digest: 'd1',
  rules: [
    { pos: 0, type: 'in', action: 'ACCEPT', proto: 'tcp', dport: '22',
      source: '10.0.0.0/24', dest: null, sport: null, enable: 1,
      comment: 'ssh from the office', digest: 'd1' },
    { pos: 1, type: 'in', action: 'DROP', proto: null, dport: null,
      source: null, dest: null, sport: null, enable: 0, comment: null,
      digest: 'd1' },
  ],
}

const calls: { path: string; method: string; body: any }[] = []

vi.mock('../api/client', () => {
  class ApiError extends Error {
    status: number; body: unknown
    constructor(status: number, body: unknown) {
      super(`API ${status}`); this.status = status; this.body = body
    }
  }
  return {
    ApiError,
    api: vi.fn((path: string, opts?: RequestInit) => {
      const method = (opts?.method ?? 'GET').toUpperCase()
      if (method !== 'GET') {
        calls.push({ path, method, body: opts?.body ? JSON.parse(String(opts.body)) : {} })
        return Promise.resolve({ ok: true })
      }
      // Only the cluster scope used by most tests below gets RULES: matching
      // any path ending in '/rules' also catches the node scope path the
      // last test uses, which is meant to resolve to {} (an unmocked scope).
      if (path === '/firewall/cluster/1/rules') return Promise.resolve(RULES)
      return Promise.resolve({})
    }),
  }
})

import { FirewallRuleTable } from '../components/FirewallRuleTable'

const SCOPE = { kind: 'cluster', hostId: 1 } as const

function renderTable(props: Partial<React.ComponentProps<typeof FirewallRuleTable>> = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <FirewallRuleTable scope={SCOPE} canEdit onEdit={() => {}} onAdd={() => {}}
        {...props} />
    </QueryClientProvider>,
  )
}

describe('FirewallRuleTable', () => {
  it('lists rules in position order with their direction and action', async () => {
    renderTable()
    await screen.findByText('ssh from the office')
    const rows = screen.getAllByRole('row').slice(1)   // drop the header
    expect(rows).toHaveLength(2)
    expect(rows[0]).toHaveTextContent('ACCEPT')
    expect(rows[1]).toHaveTextContent('DROP')
  })

  it('shows a disabled rule as off rather than hiding it', async () => {
    // A rule PVE is storing but not applying still governs what the operator
    // thinks is configured, so it is shown and marked, never omitted.
    renderTable()
    await screen.findByText('ssh from the office')
    expect(screen.getByLabelText('Rule 1 is off')).toBeTruthy()
  })

  it('says which ports and addresses a rule matches', async () => {
    renderTable()
    await screen.findByText('ssh from the office')
    expect(screen.getByText('10.0.0.0/24')).toBeTruthy()
    expect(screen.getByText('tcp/22')).toBeTruthy()
  })

  it('reads "any" where PVE stored nothing, not an empty cell', async () => {
    renderTable()
    await screen.findByText('ssh from the office')
    // Rule 1 has no source, dest, proto or ports at all.
    expect(screen.getAllByText('any').length).toBeGreaterThan(0)
  })

  it('moves a rule up by sending moveto with the digest', async () => {
    calls.length = 0
    renderTable()
    await screen.findByText('ssh from the office')
    fireEvent.click(screen.getByLabelText('Move rule 1 up'))
    await waitFor(() => expect(calls).toHaveLength(1))
    expect(calls[0].path).toBe('/firewall/cluster/1/rules/1/move')
    expect(calls[0].body).toEqual({ moveto: 0, digest: 'd1' })
  })

  it('does not offer to move the first rule up or the last one down', async () => {
    renderTable()
    await screen.findByText('ssh from the office')
    expect(screen.queryByLabelText('Move rule 0 up')).toBeNull()
    expect(screen.queryByLabelText('Move rule 1 down')).toBeNull()
  })

  it('toggles a rule on by patching enable, leaving everything else alone', async () => {
    calls.length = 0
    renderTable()
    await screen.findByText('ssh from the office')
    fireEvent.click(screen.getByLabelText('Turn rule 1 on'))
    await waitFor(() => expect(calls).toHaveLength(1))
    expect(calls[0].method).toBe('PUT')
    expect(calls[0].body).toEqual({ enable: 1, digest: 'd1' })
  })

  it('hides every control when the viewer cannot edit', async () => {
    renderTable({ canEdit: false })
    await screen.findByText('ssh from the office')
    expect(screen.queryByLabelText('Move rule 1 up')).toBeNull()
    expect(screen.queryByRole('button', { name: /add rule/i })).toBeNull()
  })

  it('says the list is empty rather than drawing an empty table', async () => {
    // An empty rule list is the normal state of a firewall nobody has
    // configured, so it gets a sentence, not a header row over nothing.
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={qc}>
        <FirewallRuleTable scope={{ kind: 'node', hostId: 1, node: 'pve1' }}
          canEdit onEdit={() => {}} onAdd={() => {}} />
      </QueryClientProvider>,
    )
    // The node path is not mocked above, so it resolves to {} and rules is
    // undefined: the same render path as a genuinely empty list.
    await waitFor(() => expect(screen.getByText(/no rules/i)).toBeTruthy())
  })
})
