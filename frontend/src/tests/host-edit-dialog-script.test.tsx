import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

// The gap this closes: the Edit dialog for an existing host offered fields
// to paste a capability token into, but no way to reach the script that
// produces one. These tests cover reaching HostScriptPanel from there, and
// that the capabilities it asks for default to what the host is missing.
//
// Retargeted from the now-deleted HostTokensDialog, which HostEditDialog
// absorbed: the script panel behaviour below is unchanged, only the dialog
// hosting it is.

let capabilities: Record<string, boolean> = {
  monitoring: true, lifecycle: true, console: false, backup: false,
}
const scriptCalls: { capabilities: string[]; node_shell: boolean; node_power: boolean }[] = []
const scriptResult = { script: "# Proxploy\npveum user add proxploy@pve --comment 'Proxploy'\n" }

vi.mock('../api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/client')>()),
  api: vi.fn((path: string, opts?: RequestInit) => {
    if (path === '/hosts/token-script' && opts?.body) {
      scriptCalls.push(JSON.parse(String(opts.body)))
      return Promise.resolve(scriptResult)
    }
    if (path === '/hosts/3' && !opts?.method) {
      return Promise.resolve({ id: 3, name: 'pve-01', capabilities })
    }
    return Promise.resolve({})
  }),
}))

import { HostEditDialog } from '../components/HostEditDialog'

const host = { name: 'pve-01', address: 'https://10.0.0.5:8006' }

const wrap = () => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>
    <HostEditDialog hostId={3} host={host} onClose={() => {}} />
  </QueryClientProvider>)
}

describe('HostEditDialog setup script', () => {
  beforeEach(() => {
    scriptCalls.length = 0
    capabilities = { monitoring: true, lifecycle: true, console: false, backup: false }
  })
  afterEach(() => vi.restoreAllMocks())

  it('generates and shows the script from the Edit dialog, the same generator HostForm uses', async () => {
    wrap()
    fireEvent.click(await screen.findByRole('button', { name: 'Generate setup script' }))
    expect(await screen.findByText(/pveum user add proxploy@pve/)).toBeInTheDocument()
    expect(scriptCalls).toHaveLength(1)
  })

  it('says the pveum user add line fails harmlessly if that user already exists', async () => {
    wrap()
    fireEvent.click(await screen.findByRole('button', { name: 'Generate setup script' }))
    await screen.findByText(/pveum user add proxploy@pve/)
    expect(screen.getByText(/already exists on the node/i)).toBeInTheDocument()
    expect(screen.getByText(/already exists on the node/i).textContent)
      .toMatch(/fails.*everything after it still runs/i)
  })

  it('defaults the requested capabilities to the ones not yet stored for this host', async () => {
    // lifecycle is stored, console and backup are not: only the gaps should
    // be asked for, and monitoring never appears since the script always
    // includes it regardless of what is requested.
    wrap()
    // Wait for the host's capability data to actually be in, same query
    // HostCapabilityList renders from, so the default is not computed off
    // data that has not arrived yet.
    await screen.findByText('Console')
    fireEvent.click(screen.getByRole('button', { name: 'Generate setup script' }))
    await waitFor(() => expect(scriptCalls).toHaveLength(1))
    const requested = scriptCalls[0].capabilities
    expect(requested).not.toContain('lifecycle')
    expect(requested).not.toContain('monitoring')
    expect(requested.sort()).toEqual(['backup', 'console'])
  })

  it('still offers Generate, asking for everything, when every capability is already stored', async () => {
    capabilities = { monitoring: true, lifecycle: true, console: true, backup: true }
    wrap()
    await screen.findByText('Console')
    const btn = screen.getByRole('button', { name: 'Generate setup script' })
    expect(btn).toBeEnabled()
    fireEvent.click(btn)
    await waitFor(() => expect(scriptCalls).toHaveLength(1))
    expect(scriptCalls[0].capabilities.sort()).toEqual(['backup', 'console', 'lifecycle'])
  })
})
