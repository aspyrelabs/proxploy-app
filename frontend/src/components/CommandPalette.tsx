import { useEffect, useState, useSyncExternalStore } from 'react'
import { Command } from 'cmdk'
import { useNavigate } from '@tanstack/react-router'
import { useEntitlements } from '../api/hooks'
import { useGlobalSearch } from '../api/search'
import type { SearchResult } from '../api/search'
import { Dialog } from './ui/dialog'

// The trigger (Topbar's search button) and the palette (mounted once in
// AppShell) are siblings, and there is no shared Dialog primitive to route
// state through, so this is the smallest way to let one open what the other
// renders: a module-level flag plus React's built-in external-store hook,
// same shape the router-search-param hooks elsewhere in this app already use
// for cross-component overlay state, minus the URL persistence this doesn't need.
let paletteOpen = false
const listeners = new Set<() => void>()
function setPaletteOpen(v: boolean): void {
  paletteOpen = v
  listeners.forEach((l) => l())
}
function subscribe(cb: () => void): () => void {
  listeners.add(cb)
  return () => listeners.delete(cb)
}
export function openCommandPalette(): void {
  setPaletteOpen(true)
}

const GROUP_LABELS: Record<SearchResult['kind'], string> = {
  app: 'Apps', vm: 'VMs', host: 'Hosts', store: 'Store',
}
const GROUP_ORDER: SearchResult['kind'][] = ['app', 'vm', 'host', 'store']

function groupResults(results: SearchResult[]) {
  return GROUP_ORDER
    .map((kind) => ({ kind, label: GROUP_LABELS[kind], items: results.filter((r) => r.kind === kind) }))
    .filter((g) => g.items.length > 0)
}

export function CommandPalette() {
  const open = useSyncExternalStore(subscribe, () => paletteOpen)
  const navigate = useNavigate()
  const ent = useEntitlements()
  // has() reads false until the first entitlements fetch resolves; gating on
  // !has() alone would show the locked message to every plan during load
  // (same guard as AttachmentMap in routes/network.tsx).
  const denied = ent.data != null && !ent.has('ui.global_search')
  const [raw, setRaw] = useState('')
  const [query, setQuery] = useState('')

  const search = useGlobalSearch(query, open && !denied)
  const groups = groupResults(search.data?.results ?? [])
  const flat = groups.flatMap((g) => g.items)

  const close = (): void => setPaletteOpen(false)

  // Debounce: /search is a LIKE scan server-side, wait for a pause in typing.
  // Under 2 characters, skip the request entirely, the server would return
  // an empty array anyway.
  useEffect(() => {
    const trimmed = raw.trim()
    if (trimmed.length < 2) { setQuery(''); return }
    const t = setTimeout(() => setQuery(trimmed), 250)
    return () => clearTimeout(t)
  }, [raw])

  // Focus restore used to live here. The shared Dialog primitive captures the
  // opening element and puts focus back, the same as every other overlay.
  useEffect(() => {
    if (!open) return
    setRaw('')
    setQuery('')
  }, [open])

  // The only global keydown listener in the app: registered once for the
  // component's whole (app-length) lifetime and cleaned up on unmount. Escape
  // is no longer handled here; Radix owns it now, along with the focus trap.
  useEffect(() => {
    function onKeyDown(e: globalThis.KeyboardEvent): void {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        // A dead shortcut is worse than a locked one: this opens even for a
        // viewer without ui.global_search, the dialog itself shows the plan
        // message instead of doing nothing.
        setPaletteOpen(true)
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [])

  if (!open) return null

  const go = (r: SearchResult): void => {
    close()
    navigate({ to: r.href as never })
  }

  return (
    <Dialog title="Search" variant="palette" width={560} onClose={close}>
      {/* shouldFilter={false}: the result set is already the server's answer to
          this query. Letting cmdk filter it again would hide rows the backend
          matched on fields the label does not show. */}
      <Command shouldFilter={false} loop label="Search apps, VMs, hosts and the store">
        <Command.Input
          autoFocus
          disabled={denied}
          title={denied ? 'Not included in your plan' : undefined}
          className="w-full rounded-ctl border border-line bg-panel-2 px-3 py-2 text-[14px] text-text outline-none disabled:opacity-60"
          placeholder="Search apps, VMs, hosts, the store…"
          value={raw}
          onValueChange={setRaw}
        />

        {denied ? (
          <p className="mt-3 px-1 text-[12.5px] text-text-3">
            Global search is not included in your plan. Upgrade to search apps, VMs, hosts and
            the store from anywhere.
          </p>
        ) : (
          <Command.List className="mt-2 max-h-[50vh] overflow-auto">
            {raw.trim().length > 0 && raw.trim().length < 2 ? (
              <p className="px-2 py-3 text-[12.5px] text-text-3">Keep typing, 2 characters minimum.</p>
            ) : query.length === 0 ? (
              <p className="px-2 py-3 text-[12.5px] text-text-3">Type to search across the fleet.</p>
            ) : search.isFetching && flat.length === 0 ? (
              <p className="px-2 py-3 text-[12.5px] text-text-3">Searching…</p>
            ) : flat.length === 0 ? (
              <p className="px-2 py-3 text-[12.5px] text-text-3">No results for &quot;{query}&quot;.</p>
            ) : (
              groups.map((g) => (
                <Command.Group key={g.kind} heading={g.label} className="mb-1
                  [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1
                  [&_[cmdk-group-heading]]:text-[11px] [&_[cmdk-group-heading]]:uppercase
                  [&_[cmdk-group-heading]]:tracking-wide [&_[cmdk-group-heading]]:text-text-3">
                  {g.items.map((r) => (
                    <Command.Item
                      key={`${r.kind}-${r.id}`}
                      value={`${r.kind}-${r.id}`}
                      onSelect={() => go(r)}
                      className="flex cursor-pointer items-center justify-between rounded-ctl px-2 py-1.5 text-[13px] text-text-2 data-[selected=true]:bg-elev data-[selected=true]:text-text"
                    >
                      <span>
                        {r.label}
                        {r.sublabel && <span className="ml-2 text-[11.5px] text-text-3">{r.sublabel}</span>}
                      </span>
                      {r.status && <span className="text-[11px] text-text-3">{r.status}</span>}
                    </Command.Item>
                  ))}
                </Command.Group>
              ))
            )}
          </Command.List>
        )}
      </Command>
    </Dialog>
  )
}
