import { createRoute, useParams } from '@tanstack/react-router'
import { AppLogs } from './apps'
import { rootRoute } from './shell'

/** Logs get a window of their own rather than a tab on the app detail page:
 *  they stay open beside whatever you're doing, and a tab you leave stops
 *  showing the transcript.
 *
 *  Child of rootRoute rather than shellRoute (like consoleWindowRoute): this
 *  opens via window.open (openLogsWindow in lib/console-window.ts), and a
 *  popup shouldn't carry the sidebar/topbar chrome.
 *
 *  Its own route rather than a case in ConsoleWindow because it isn't a
 *  console — no ticket, websocket, or reconnect loop, just AppLogs' useQuery
 *  against GET /apps/{id}/logs — so reusing that ticket-shaped state machine
 *  would mean threading a fake-console kind through it.
 */
function LogsWindow() {
  const { appId: rawId } = useParams({ strict: false }) as { appId: string }
  const appId = Number(rawId)
  // Same bg-ink frame as ConsoleWindow's Failure view, so the two popups read
  // as siblings; padded because AppLogs' panels already carry their own
  // borders (not edge-to-edge like the console's xterm surface).
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
