import { Outlet, createRootRoute, createRoute, redirect } from '@tanstack/react-router'
import { api } from '../api/client'
import { AppShell } from '../components/AppShell'
import { LiveProvider } from '../components/LiveProvider'

export const rootRoute = createRootRoute({ component: () => <Outlet /> })

type Onboarding = { admin_exists: boolean; host_added: boolean; complete: boolean }

// Split out of router.tsx: route files need `shellRoute` as their parent, and
// router.tsx needs the route files to assemble routeTree/createRouter (which
// runs eagerly at module scope). Route files import shellRoute from *here*,
// not from router.tsx, so importing a route file directly (as a test does)
// never forces router.tsx's eager Router construction to run mid-cycle with
// half-initialized route objects.
export const shellRoute = createRoute({
  id: 'shell',
  getParentRoute: () => rootRoute,
  component: () => (
    <LiveProvider>
      <AppShell />
    </LiveProvider>
  ),
  beforeLoad: async () => {
    const ob = await api<Onboarding>('/meta/onboarding')
    if (!ob.complete) throw redirect({ to: '/onboarding' })
    try { await api('/auth/me') } catch { throw redirect({ to: '/login' }) }
  },
})
