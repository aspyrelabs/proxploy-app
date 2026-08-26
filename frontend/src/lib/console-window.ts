import type { ConsoleKind } from '../api/consoles'

/** Consoles open in a window of their own, not a tab on the page they came
 *  from: navigating a tab away kills the session behind it.
 *
 *  The window NAME is the load-bearing part — stable per target, so a second
 *  click focuses the window already open instead of redeeming another
 *  single-use ticket and starting another PTY against the same guest.
 *  `noopener,noreferrer` so the console window gets no `window.opener` handle.
 */
export function consoleWindowName(kind: ConsoleKind, id: number): string {
  return `proxploy-console-${kind}-${id}`
}

export function consoleWindowPath(kind: ConsoleKind, id: number): string {
  return `/shell/${kind}/${id}`
}

/** A terminal is text at a readable size; a VM console is somebody's DESKTOP,
 *  arriving at whatever resolution the guest booted at. Opening 1024x768 or
 *  1080p into a terminal-sized window means it is scaled down or scrolling
 *  from the first frame, so VNC gets more room to start with. */
const SIZE: Record<ConsoleKind, string> = {
  host: 'width=1040,height=660',
  app: 'width=1040,height=660',
  vm: 'width=1280,height=800',
}

export function openConsoleWindow(kind: ConsoleKind, id: number): void {
  window.open(consoleWindowPath(kind, id), consoleWindowName(kind, id),
              `${SIZE[kind]},noopener,noreferrer`)
}

/** An app's logs, same treatment: a window of their own instead of a tab on
 *  the app detail page. The window NAME is stable per app for the same
 *  reason as consoleWindowName: a second click on Logs should focus the
 *  window already open, not stack another one behind it. */
export function logsWindowName(appId: number): string {
  return `proxploy-logs-app-${appId}`
}

export function logsWindowPath(appId: number): string {
  return `/logs/app/${appId}`
}

export function openLogsWindow(appId: number): void {
  window.open(logsWindowPath(appId), logsWindowName(appId),
              'width=1040,height=660,noopener,noreferrer')
}
