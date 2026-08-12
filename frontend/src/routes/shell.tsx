import { Outlet, createRootRoute, createRoute, redirect } from '@tanstack/react-router'
import { ApiError, api } from '../api/client'
import { AppShell } from '../components/AppShell'
import { LiveProvider } from '../components/LiveProvider'
import { RouteError } from '../components/RouteError'
import { LoadingBlock } from '../components/ui/loading'

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
  errorComponent: RouteError,
  // beforeLoad below chains two awaited requests before anything mounts, and
  // no defaultPendingComponent is set at the router level, so without this
  // the very first paint of the app is a blank page for as long as those
  // requests take. There is no completion signal for "how much of onboarding
  // and auth is left to check", so this is the indeterminate ring, never a
  // number.
  pendingComponent: () => (
    <div className="grid min-h-screen place-items-center">
      <LoadingBlock label="Loading Proxploy" />
    </div>
  ),
  beforeLoad: async () => {
    // Left uncaught on purpose: errorComponent above is what renders this
    // failure now (finding F1). A 500 or an unreachable backend here must not
    // read as "you have not onboarded"; that would bounce a fully set-up
    // user back into the wizard.
    const ob = await api<Onboarding>('/meta/onboarding')
    if (!ob.complete) throw redirect({ to: '/onboarding' })
    try {
      await api('/auth/me')
    } catch (e) {
      // redirect() throws a Response, not an ApiError, so this check never
      // catches a redirect thrown above, only a real /auth/me failure lands
      // here. Only a 401 means "please sign in"; any other failure (a 500,
      // a network error) is not that, and must reach errorComponent instead
      // of silently masquerading as a logged-out user.
      if (e instanceof ApiError && e.status === 401) throw redirect({ to: '/login' })
      throw e
    }
  },
})
