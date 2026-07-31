import { createRoute, createRouter, redirect } from '@tanstack/react-router'
import { rootRoute, shellRoute } from './routes/shell'

export { rootRoute, shellRoute }

export const indexRoute = createRoute({
  getParentRoute: () => rootRoute, path: '/',
  // cast: indexRoute's own `to` type can't see the tree it's still being built into
  beforeLoad: () => { throw redirect({ to: '/cluster' as never }) },
})

import { loginRoute } from './routes/login'
import { onboardingRoute } from './routes/onboarding'
import { settingsRoute } from './routes/settings'
import { clusterRoute, nodeDetailRoute } from './routes/cluster'
import { appsRoute, appDetailRoute, appOverviewRoute, appLogsRoute, appConsoleRoute, appConfigRoute } from './routes/apps'
import { vmsRoute, vmDetailRoute, vmOverviewRoute, vmConsoleRoute, vmSnapshotsRoute } from './routes/vms'
import { storeRoute } from './routes/store'
import { storageRoute } from './routes/storage'
import { networkRoute } from './routes/network'
import { backupsRoute } from './routes/backups'

const appDetailTree = appDetailRoute.addChildren([appOverviewRoute, appLogsRoute, appConsoleRoute, appConfigRoute])
const vmDetailTree = vmDetailRoute.addChildren([vmOverviewRoute, vmConsoleRoute, vmSnapshotsRoute])

export const routeTree = rootRoute.addChildren([
  indexRoute, loginRoute, onboardingRoute,
  shellRoute.addChildren([clusterRoute, nodeDetailRoute, appsRoute, appDetailTree, storeRoute, vmsRoute, vmDetailTree,
                          storageRoute, networkRoute, backupsRoute, settingsRoute]),
])
export const router = createRouter({ routeTree })

declare module '@tanstack/react-router' {
  interface Register { router: typeof router }
}
