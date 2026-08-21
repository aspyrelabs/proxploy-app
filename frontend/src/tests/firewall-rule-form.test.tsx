import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

const REFS = { refs: [
  { type: 'alias', name: 'office', ref: 'office', comment: 'the office range' },
  { type: 'ipset', name: 'trusted', ref: '+trusted' },
] }
const MACROS = { macros: [
  { macro: 'Web', descr: 'WWW traffic (HTTP and HTTPS)' },
  { macro: 'SSH', descr: 'Secure shell traffic' },
] }
const GROUPS = { groups: [{ group: 'web', comment: 'public services' }] }

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
      if (path.endsWith('/refs')) return Promise.resolve(REFS)
      if (path.endsWith('/macros')) return Promise.resolve(MACROS)
      if (path.endsWith('/groups')) return Promise.resolve(GROUPS)
      return Promise.resolve({ rules: [], digest: null })
    }),
  }
})

import { FirewallRuleForm } from '../components/FirewallRuleForm'

const SCOPE = { kind: 'cluster', hostId: 1 } as const

function renderForm(rule: any = null) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <FirewallRuleForm scope={SCOPE} hostId={1} rule={rule} onClose={() => {}} />
    </QueryClientProvider>,
  )
}

describe('FirewallRuleForm', () => {
  it('keeps macro, interface, log level and icmp type out of the way', () => {
    renderForm()
    expect(screen.getByLabelText('Direction')).toBeTruthy()
    expect(screen.queryByLabelText('Macro')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: /advanced/i }))
    expect(screen.getByLabelText('Macro')).toBeTruthy()
    expect(screen.getByLabelText('Log level')).toBeTruthy()
  })

  it('creates a rule with the fields that were filled in and no others', async () => {
    calls.length = 0
    renderForm()
    fireEvent.change(screen.getByLabelText('Protocol'), { target: { value: 'tcp' } })
    fireEvent.change(screen.getByLabelText('Destination port'), { target: { value: '443' } })
    fireEvent.change(screen.getByLabelText('Comment'), { target: { value: 'https' } })
    fireEvent.click(screen.getByRole('button', { name: /save rule/i }))
    await waitFor(() => expect(calls).toHaveLength(1))
    expect(calls[0].method).toBe('POST')
    expect(calls[0].body).toEqual({
      type: 'in', action: 'ACCEPT', enable: 1, proto: 'tcp', dport: '443',
      comment: 'https',
    })
  })

  it('sends icmp-type hyphenated, never icmp_type', async () => {
    // The wire name has a hyphen. A snake_case field name here reaches PVE as
    // an unknown parameter and the icmp type is silently dropped.
    calls.length = 0
    renderForm()
    fireEvent.change(screen.getByLabelText('Protocol'), { target: { value: 'icmp' } })
    fireEvent.click(screen.getByRole('button', { name: /advanced/i }))
    fireEvent.change(screen.getByLabelText('ICMP type'),
      { target: { value: 'echo-request' } })
    fireEvent.click(screen.getByRole('button', { name: /save rule/i }))
    await waitFor(() => expect(calls).toHaveLength(1))
    expect(calls[0].body['icmp-type']).toBe('echo-request')
    expect(calls[0].body.icmp_type).toBeUndefined()
  })

  it('offers existing aliases and IP sets for source and destination', async () => {
    renderForm()
    await screen.findByText('+trusted')
    const source = screen.getByLabelText('Source') as HTMLInputElement
    expect(source.getAttribute('list')).toBeTruthy()
    // The IP set is offered in the form a rule actually uses, with its +.
    expect(screen.getAllByText('+trusted').length).toBeGreaterThan(0)
  })

  it('offers security groups as an action alongside accept, drop and reject',
     async () => {
    renderForm()
    await screen.findByRole('option', { name: 'web' })
    const action = screen.getByLabelText('Action') as HTMLSelectElement
    const values = Array.from(action.options).map(o => o.value)
    expect(values).toEqual(expect.arrayContaining(['ACCEPT', 'DROP', 'REJECT', 'web']))
  })

  it('edits an existing rule by PUTting only what changed, with the digest',
     async () => {
    calls.length = 0
    renderForm({ pos: 2, type: 'in', action: 'ACCEPT', proto: 'tcp',
                 dport: '22', enable: 1, comment: 'ssh', digest: 'd1' })
    fireEvent.change(screen.getByLabelText('Comment'),
      { target: { value: 'ssh from anywhere' } })
    fireEvent.click(screen.getByRole('button', { name: /save rule/i }))
    await waitFor(() => expect(calls).toHaveLength(1))
    expect(calls[0].method).toBe('PUT')
    expect(calls[0].path).toBe('/firewall/cluster/1/rules/2')
    expect(calls[0].body.comment).toBe('ssh from anywhere')
    expect(calls[0].body.digest).toBe('d1')
  })

  it('shows a macro description, because the name alone does not say what it does',
     async () => {
    renderForm()
    fireEvent.click(screen.getByRole('button', { name: /advanced/i }))
    await screen.findByText(/WWW traffic/)
  })

  it('says a new rule will be checked before the existing ones', () => {
    renderForm()
    expect(screen.getByText(/goes to the top of the list/i)).toBeTruthy()
  })

  it('does not say it when editing an existing rule', () => {
    renderForm({ pos: 2, type: 'in', action: 'ACCEPT', enable: 1, digest: 'd1' })
    expect(screen.queryByText(/goes to the top of the list/i)).toBeNull()
  })
})
