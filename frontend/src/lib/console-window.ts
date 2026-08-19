import type { ConsoleKind } from '../api/consoles'

/** Every console (node shell, app console, VM console) opens in a window of
 *  its own rather than in a tab on the page it came from.
 *
 *  A console is a working surface you keep beside the page while you do
 *  something else with it; a tab is a place you navigate to, and navigating
 *  away from a tab kills the session behind it.
 *
 *  The window NAME is the load-bearing part. It is stable per target, so a
 *  second click on Console focuses the window that is already open instead of
 *  opening another one. Without it, every click would redeem another
 *  single-use ticket and start another PTY against the same guest, which is
 *  the situation the ticket design exists to prevent.
 *
 *  `noopener,noreferrer` for the usual reason: the console window gets no
 *  handle on the app window through `window.opener`.
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
