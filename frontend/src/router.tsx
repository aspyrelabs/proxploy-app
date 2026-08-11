import { createRoute, createRouter, redirect } from '@tanstack/react-router'
import { RouteError } from './components/RouteError'
import { rootRoute, shellRoute } from './routes/shell'

export { rootRoute, shellRoute }

export const indexRoute = createRoute({
  getParentRoute: () => rootRoute, path: '/',
  // cast: indexRoute's own `to` type can't see the tree it's still being built into
  beforeLoad: () => { throw redirect({ to: '/hosts' as never }) },
})

import { loginRoute } from './routes/login'
import { onboardingRoute } from './routes/onboarding'
import { alertsRoute } from './routes/alerts'
import { settingsRoute } from './routes/settings'
import { hostsRoute, nodeDetailRoute } from './routes/hosts'
import { appsRoute, appDetailRoute, appOverviewRoute, appLogsRoute, appConsoleRoute, appConfigRoute } from './routes/apps'
import { vmsRoute, vmDetailRoute, vmOverviewRoute, vmConsoleRoute, vmSnapshotsRoute } from './routes/vms'
import { storeRoute } from './routes/store'
import { storageRoute } from './routes/storage'
import { networkRoute } from './routes/network'
import { backupsRoute } from './routes/backups'
import { auditRoute } from './routes/audit'

const appDetailTree = appDetailRoute.addChildren([appOverviewRoute, appLogsRoute, appConsoleRoute, appConfigRoute])
const vmDetailTree = vmDetailRoute.addChildren([vmOverviewRoute, vmConsoleRoute, vmSnapshotsRoute])

export const routeTree = rootRoute.addChildren([
  indexRoute, loginRoute, onboardingRoute,
  shellRoute.addChildren([hostsRoute, nodeDetailRoute, appsRoute, appDetailTree, storeRoute, vmsRoute, vmDetailTree,
                          storageRoute, networkRoute, backupsRoute, alertsRoute, settingsRoute, auditRoute]),
])
export const router = createRouter({ routeTree, defaultErrorComponent: RouteError })

declare module '@tanstack/react-router' {
  interface Register { router: typeof router }
}
