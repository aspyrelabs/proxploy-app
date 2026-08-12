/**
 * Minimal EventSource stand-in for JobLog's live subscription.
 *
 * jsdom has no EventSource at all, and JobLog checks
 * `typeof EventSource === 'undefined'` and skips the live stream entirely
 * when it's missing (src/components/JobLog.tsx), so a test that wants to
 * exercise the live path (a `progress` frame driving a ring, say) has to
 * install one first.
 *
 * Install with `installFakeEventSource()` in the test body (or a
 * `beforeEach`), call the returned function to uninstall, and reach the most
 * recently constructed instance through `FakeEventSource.last` to fire
 * events at it.
 */
export class FakeEventSource {
  static instances: FakeEventSource[] = []
  static get last(): FakeEventSource {
    return FakeEventSource.instances[FakeEventSource.instances.length - 1]
  }

  url: string
  closed = false
  listeners: Record<string, ((e: MessageEvent) => void)[]> = {}

  constructor(url: string) {
    this.url = url
    FakeEventSource.instances.push(this)
  }

  addEventListener(type: string, cb: (e: MessageEvent) => void): void {
    (this.listeners[type] ??= []).push(cb)
  }

  close(): void {
    this.closed = true
  }

  /** Fire a named SSE frame at every listener registered for it, JSON-encoded
   *  exactly as the real stream would send it (JobLog does `JSON.parse(e.data)`). */
  emit(type: string, data: unknown): void {
    for (const cb of this.listeners[type] ?? []) {
      cb({ data: JSON.stringify(data) } as MessageEvent)
    }
  }
}

export function installFakeEventSource(): () => void {
  FakeEventSource.instances = []
  const prev = (globalThis as { EventSource?: unknown }).EventSource
  ;(globalThis as { EventSource?: unknown }).EventSource = FakeEventSource
  return () => {
    (globalThis as { EventSource?: unknown }).EventSource = prev
  }
}
