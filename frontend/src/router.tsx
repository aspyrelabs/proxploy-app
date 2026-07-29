import { Outlet, createRootRoute, createRoute, createRouter, redirect } from '@tanstack/react-router'
import { api } from './api/client'
import { AppShell } from './components/AppShell'
import { PlaceholderPage } from './routes/placeholder'

export const rootRoute = createRootRoute({ component: () => <Outlet /> })

type Onboarding = { admin_exists: boolean; host_added: boolean; complete: boolean }

export const shellRoute = createRoute({
  id: 'shell',
  getParentRoute: () => rootRoute,
  component: AppShell,
  beforeLoad: async () => {
    const ob = await api<Onboarding>('/meta/onboarding')
    // '/onboarding' lands in the route tree in Task 15; cast until then
    if (!ob.complete) throw redirect({ to: '/onboarding' as never })
    try { await api('/auth/me') } catch { throw redirect({ to: '/login' }) }
  },
})

const page = (path: string, title: string, phase: string, note: string) =>
  createRoute({
    getParentRoute: () => shellRoute,
    path,
    component: () => <PlaceholderPage title={title} phase={phase} note={note} />,
  })

export const indexRoute = createRoute({
  getParentRoute: () => rootRoute, path: '/',
  // cast: indexRoute's own `to` type can't see the tree it's still being built into
  beforeLoad: () => { throw redirect({ to: '/cluster' as never }) },
})

export const clusterRoute = page('/cluster', 'Cluster', 'Phase 2 (Observe)',
  'Fleet rings, node cards and the live dashboard arrive with the poller subsystem.')
export const appsRoute = page('/apps', 'Apps', 'Phase 2 (Observe)',
  'Installed apps are discovered by the poller; the grid renders here.')
export const storeRoute = page('/store', 'App Store', 'Phase 4 (Store)',
  'The community-scripts catalog is fetched and cached server-side, never from the browser.')
export const vmsRoute = page('/vms', 'Virtual Machines', 'Phase 2 (Observe)',
  'The VM table renders from the poller cache.')
export const storageRoute = page('/storage', 'Storage', 'Phase 6 (Infra pages)',
  'Datastore cards and the content browser arrive in Phase 6.')
export const networkRoute = page('/network', 'Network', 'Phase 6 (Infra pages)',
  'Bridges, VLANs and throughput arrive in Phase 6.')
export const backupsRoute = page('/backups', 'Backups', 'Phase 6 (Infra pages)',
  'PBS integration arrives in Phase 6.')

import { loginRoute } from './routes/login'

export const routeTree = rootRoute.addChildren([
  indexRoute, loginRoute,
  shellRoute.addChildren([clusterRoute, appsRoute, storeRoute, vmsRoute,
                          storageRoute, networkRoute, backupsRoute]),
])
export const router = createRouter({ routeTree })

declare module '@tanstack/react-router' {
  interface Register { router: typeof router }
}
