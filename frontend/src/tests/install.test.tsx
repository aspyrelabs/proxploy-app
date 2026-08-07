import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { InstallDialog } from '../components/InstallDialog'

vi.mock('../api/client', () => ({ api: vi.fn() }))

function renderDialog() {
  const qc = new QueryClient()
  return render(
    <QueryClientProvider client={qc}>
      <InstallDialog slug="redis" onClose={vi.fn()} />
    </QueryClientProvider>,
  )
}

describe('InstallDialog', () => {
  it('disables Install until consent is checked, then submits with consent:true', async () => {
    const { api } = await import('../api/client')
    vi.mocked(api).mockImplementation((path: string) => {
      if (path === '/catalog/redis') return Promise.resolve({
        slug: 'redis', name: 'Redis', default_cpu: 1, default_ram_mb: 1024,
        default_disk_gb: 4, installable: true, raw: { install_script: 'msg_ok done' },
      })
      if (path === '/hosts') return Promise.resolve([{ id: 1, name: 'host-01' }])
      if (path === '/catalog/redis/install') return Promise.resolve({ job: { id: 9, kind: 'app.install' } })
      return Promise.resolve(null)
    })

    renderDialog()
    await waitFor(() => expect(screen.getByText(/runs as root on/i)).toBeInTheDocument())
    const installBtn = screen.getByRole('button', { name: 'Install' })
    expect(installBtn).toBeDisabled()

    // Fill host/name/ctid, button must stay disabled until consent is also checked.
    fireEvent.change(screen.getByRole('combobox'), { target: { value: '1' } })
    fireEvent.change(screen.getByPlaceholderText('App name'), { target: { value: 'redis-1' } })
    fireEvent.change(screen.getByPlaceholderText('Container ID (CTID)'), { target: { value: '105' } })
    expect(installBtn).toBeDisabled()

    fireEvent.click(screen.getByRole('checkbox'))
    expect(installBtn).toBeEnabled()
    fireEvent.click(installBtn)

    await waitFor(() => expect(api).toHaveBeenCalledWith('/catalog/redis/install', expect.objectContaining({
      method: 'POST',
      body: expect.stringContaining('"consent":true'),
    })))
  })
})
