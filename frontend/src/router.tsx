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
import { logsWindowRoute } from './routes/logs-window'
import { onboardingRoute } from './routes/onboarding'
import { alertsRoute } from './routes/alerts'
import { settingsRoute } from './routes/settings'
import { hostsRoute, nodeDetailRoute, hostEntryRoute, hostOverviewRoute, hostHardwareRoute } from './routes/hosts'
import { profileRoute } from './routes/profile'
import { appsRoute } from './routes/apps'
import { vmsRoute } from './routes/vms'
import { storeRoute } from './routes/store'
import { storeDetailRoute } from './routes/store-detail'
import { storageRoute } from './routes/storage'
import { networkRoute } from './routes/network'
import { backupsRoute } from './routes/backups'
import { auditRoute } from './routes/audit'

const nodeDetailTree = nodeDetailRoute.addChildren([hostOverviewRoute, hostHardwareRoute])
// No console child: consoles open in a window of their own
// (lib/console-window.ts), not as a tab under the detail page.
// No VM detail tree either: a VM is a row on /vms that expands in place, with
// its snapshots inside that panel (components/VmTable.tsx).

export const routeTree = rootRoute.addChildren([
  // consoleWindowRoute and logsWindowRoute hang off the root, not the shell:
  // both are opened in a window of their own and neither wants the sidebar
  // and topbar.
  indexRoute, loginRoute, onboardingRoute, consoleWindowRoute, logsWindowRoute,
  shellRoute.addChildren([hostsRoute, nodeDetailTree, hostEntryRoute, appsRoute, storeRoute, storeDetailRoute, vmsRoute,
                          storageRoute, networkRoute, backupsRoute, alertsRoute, settingsRoute, auditRoute, profileRoute]),
])
export const router = createRouter({ routeTree, defaultErrorComponent: RouteError })

declare module '@tanstack/react-router' {
  interface Register { router: typeof router }
}
