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
import { consoleWindowRoute } from './routes/console-window'
import { onboardingRoute } from './routes/onboarding'
import { alertsRoute } from './routes/alerts'
import { settingsRoute } from './routes/settings'
import { hostsRoute, nodeDetailRoute, hostEntryRoute, hostOverviewRoute, hostHardwareRoute } from './routes/hosts'
import { profileRoute } from './routes/profile'
import { appsRoute, appDetailRoute, appOverviewRoute, appLogsRoute, appConfigRoute } from './routes/apps'
import { vmsRoute, vmDetailRoute, vmOverviewRoute, vmSnapshotsRoute } from './routes/vms'
import { storeRoute } from './routes/store'
import { storeDetailRoute } from './routes/store-detail'
import { storageRoute } from './routes/storage'
import { networkRoute } from './routes/network'
import { backupsRoute } from './routes/backups'
import { auditRoute } from './routes/audit'

const nodeDetailTree = nodeDetailRoute.addChildren([hostOverviewRoute, hostHardwareRoute])
const appDetailTree = appDetailRoute.addChildren([appOverviewRoute, appLogsRoute, appConfigRoute])
// No console child: consoles open in a window of their own
// (lib/console-window.ts), not as a tab under the detail page.
const vmDetailTree = vmDetailRoute.addChildren([vmOverviewRoute, vmSnapshotsRoute])

export const routeTree = rootRoute.addChildren([
  // consoleWindowRoute hangs off the root, not the shell: it is opened in a window
  // of its own and a terminal there does not want the sidebar and topbar.
  indexRoute, loginRoute, onboardingRoute, consoleWindowRoute,
  shellRoute.addChildren([hostsRoute, nodeDetailTree, hostEntryRoute, appsRoute, appDetailTree, storeRoute, storeDetailRoute, vmsRoute, vmDetailTree,
                          storageRoute, networkRoute, backupsRoute, alertsRoute, settingsRoute, auditRoute, profileRoute]),
])
export const router = createRouter({ routeTree, defaultErrorComponent: RouteError })

declare module '@tanstack/react-router' {
  interface Register { router: typeof router }
}
