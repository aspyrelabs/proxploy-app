import { createRoute, useParams } from '@tanstack/react-router'
import { AppLogs } from './apps'
import { rootRoute } from './shell'

/** An app's logs get the same treatment as its console (console-window.tsx):
 *  a window of their own instead of a tab on the app detail page. Logs are
 *  something you keep open beside whatever you're doing to the app, and a
 *  tab you navigate away from is a tab whose transcript you stop watching.
 *
 *  Deliberately a child of rootRoute rather than shellRoute, same reasoning
 *  as consoleWindowRoute: this opens via window.open (openLogsWindow in
 *  lib/console-window.ts), and a popup does not want the sidebar/topbar
 *  chrome around it.
 *
 *  This is its own route rather than a case added to ConsoleWindow because
 *  it isn't a console: there's no ticket, no websocket, no reconnect loop,
 *  just AppLogs' own useQuery against GET /apps/{id}/logs. Bolting that onto
 *  ConsoleWindow's ticket-shaped state machine would mean threading a
 *  fake-console kind through code that doesn't otherwise know logs exist.
 */
function LogsWindow() {
  const { appId: rawId } = useParams({ strict: false }) as { appId: string }
  const appId = Number(rawId)
  // Same bg-ink frame ConsoleWindow's Failure view uses, so the two popups
  // read as siblings; padded rather than full-bleed because AppLogs' own
  // panels (EmptyState, TerminalPanel) already carry their own borders and
  // aren't drawn edge-to-edge the way the console's xterm surface is.
  return (
    <div className="min-h-screen bg-ink p-8">
      <AppLogs appId={appId} />
    </div>
  )
}

export const logsWindowRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/logs/app/$appId',
  component: LogsWindow,
})
