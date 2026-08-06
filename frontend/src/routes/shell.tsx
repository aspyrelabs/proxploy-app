import { Outlet, createRootRoute, createRoute, redirect } from '@tanstack/react-router'
import { ApiError, api } from '../api/client'
import { AppShell } from '../components/AppShell'
import { LiveProvider } from '../components/LiveProvider'
import { RouteError } from '../components/RouteError'

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
  // The activity drawer overlays any page (doc 06), so its params live on the
  // pathless layout route — TanStack Router merges search schemas parent->child
  // (each route's validated search is spread onto the accumulated search, so a
  // child's own keys never strip a parent's), so declaring them once here
  // makes them legal and present on every page it wraps.
  // Explicit optional-property return type (`drawer?`/`job?`, not `T | undefined`)
  // — shellRoute is the parent of the whole tree, so an inferred type with
  // required-but-possibly-undefined keys would make `search` mandatory on
  // every `<Link to>`/`navigate` in the app, including ones with no idea
  // this route exists (e.g. TierPill's `to: '/settings'`).
  validateSearch: (s: Record<string, unknown>): { drawer?: 'activity'; job?: number } => ({
    drawer: s.drawer === 'activity' ? ('activity' as const) : undefined,
    job: s.job != null && !Number.isNaN(Number(s.job)) ? Number(s.job) : undefined,
  }),
  component: () => (
    <LiveProvider>
      <AppShell />
    </LiveProvider>
  ),
  errorComponent: RouteError,
  beforeLoad: async () => {
    // Left uncaught on purpose: errorComponent above is what renders this
    // failure now (finding F1). A 500 or an unreachable backend here must not
    // read as "you have not onboarded" — that would bounce a fully set-up
    // user back into the wizard.
    const ob = await api<Onboarding>('/meta/onboarding')
    if (!ob.complete) throw redirect({ to: '/onboarding' })
    try {
      await api('/auth/me')
    } catch (e) {
      // redirect() throws a Response, not an ApiError, so this check never
      // catches a redirect thrown above — only a real /auth/me failure lands
      // here. Only a 401 means "please sign in"; any other failure (a 500,
      // a network error) is not that, and must reach errorComponent instead
      // of silently masquerading as a logged-out user.
      if (e instanceof ApiError && e.status === 401) throw redirect({ to: '/login' })
      throw e
    }
  },
})
