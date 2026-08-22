import { useEffect, useState, useSyncExternalStore } from 'react'
import { Command } from 'cmdk'
import { useNavigate } from '@tanstack/react-router'
import { useEntitlements } from '../api/hooks'
import { useGlobalSearch } from '../api/search'
import { matchSettingsSections } from '../lib/settings-sections'
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
  // TWO GATES, mirroring backend/proxploy/api/search.py, which stopped gating
  // the whole endpoint on one flag: `ui.global_search` covers apps, VMs and
  // hosts, `store.catalog` covers the store group, and only a caller with
  // NEITHER is refused.
  //
  // The store half is not a nicety. The App Store's own search box was
  // removed (routes/store.tsx) and it never checked `ui.global_search`, so
  // telling a store.catalog plan "not included in your plan" here would take
  // away a capability they had this morning and dress it up as a UI cleanup.
  //
  // has() reads false until the first entitlements fetch resolves, so both
  // states are additionally gated on the data having arrived; without that,
  // every plan sees the locked copy during load (same guard as AttachmentMap
  // in routes/network.tsx).
  const loaded = ent.data != null
  const canSearchAll = ent.has('ui.global_search')
  const storeOnly = loaded && !canSearchAll && ent.has('store.catalog')
  const denied = loaded && !canSearchAll && !ent.has('store.catalog')
  // What this palette can actually reach, said the same way in the accessible
  // name, the placeholder and the empty state, so none of the three can
  // promise a store-only operator something they will not get.
  const scope = storeOnly ? 'the store' : 'apps, VMs, hosts and the store'
  const [raw, setRaw] = useState('')
  const [query, setQuery] = useState('')

  const search = useGlobalSearch(query, open && !denied)
  const groups = groupResults(search.data?.results ?? [])
  const flat = groups.flatMap((g) => g.items)
  // Settings sections are static client-side routes, so they are matched here
  // rather than by GET /search: there is nothing on the server to scan, and
  // making an operator wait 250ms and a round trip to reach their own settings
  // would be slower than the rail they are trying to skip. Matched off `raw`,
  // not `query`, for the same reason -- the debounce exists for the LIKE scan.
  //
  // This became worth doing when Settings grew a rail: a section now has a URL
  // (?section=), so "trusted devices" is somewhere the palette can actually
  // send you, and the Profile merge means it is no longer reachable by
  // scrolling for its heading.
  const sections = matchSettingsSections(raw.trim().length >= 2 ? raw : '')

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

  // The server hands back one string per result, and some of those strings
  // carry a query: an app now lives at /apps?open=<id> rather than at a page
  // of its own. TanStack Router does NOT parse a query out of `to`, it would
  // look for a route literally named "/apps?open=3" and find nothing, so the
  // two halves are split here and the search handed over as the object it
  // expects. Written for any href with a query rather than for that one shape,
  // because the next result kind to gain a param should not have to come back
  // and edit this.
  const goSection = (id: string): void => {
    close()
    navigate({ to: '/settings' as never, search: { section: id } as never })
  }

  const go = (r: SearchResult): void => {
    close()
    const [path, qs] = r.href.split('?')
    navigate({ to: path as never,
               search: qs ? Object.fromEntries(new URLSearchParams(qs)) as never : undefined })
  }

  return (
    <Dialog title="Search" variant="palette" width={560} onClose={close}>
      {/* shouldFilter={false}: the result set is already the server's answer to
          this query. Letting cmdk filter it again would hide rows the backend
          matched on fields the label does not show. */}
      <Command shouldFilter={false} loop label={`Search ${scope}`}>
        <Command.Input
          autoFocus
          disabled={denied}
          title={denied ? 'Not included in your plan' : undefined}
          className="w-full rounded-ctl border border-line bg-panel-2 px-3 py-2 text-[14px] text-text outline-none disabled:opacity-60"
          placeholder={storeOnly ? 'Search the store…' : 'Search apps, VMs, hosts, the store…'}
          value={raw}
          onValueChange={setRaw}
        />

        {/* Said once, up front, rather than left for the operator to infer
            from results that never contain their apps. This is what they can
            do, and then what they cannot, in that order. */}
        {storeOnly && (
          <p className="mt-2 px-1 text-[11.5px] text-text-3">
            Searching the app store. Apps, VMs and hosts need Global search, which is not
            included in your plan.
          </p>
        )}

        {denied ? (
          <p className="mt-3 px-1 text-[12.5px] text-text-3">
            Global search is not included in your plan. Upgrade to search apps, VMs, hosts and
            the store from anywhere.
          </p>
        ) : (
          <Command.List className="mt-2 max-h-[50vh] overflow-auto">
            {/* First, and without waiting: these are local, so they are on
                screen while the fleet search is still in flight. */}
            {sections.length > 0 && (
              <Command.Group heading="Settings" className="mb-1
                [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1
                [&_[cmdk-group-heading]]:text-[11px] [&_[cmdk-group-heading]]:uppercase
                [&_[cmdk-group-heading]]:tracking-wide [&_[cmdk-group-heading]]:text-text-3">
                {sections.map((sec) => (
                  <Command.Item
                    key={`settings-${sec.id}`}
                    value={`settings-${sec.id}`}
                    onSelect={() => goSection(sec.id)}
                    className="flex cursor-pointer items-center justify-between rounded-ctl px-2 py-1.5 text-[13px] text-text-2 data-[selected=true]:bg-elev data-[selected=true]:text-text"
                  >
                    <span>
                      {sec.label}
                      {/* The group, not the URL: "Profile · Your account" says
                          whose setting this is, which is the thing the rail's
                          own grouping exists to say. */}
                      <span className="ml-2 text-[11.5px] text-text-3">{sec.group}</span>
                    </span>
                    <span className="text-[11px] text-text-3">Settings</span>
                  </Command.Item>
                ))}
              </Command.Group>
            )}

            {/* Every message below is suppressed once a section matched: a
                "No results" under a list of results is a lie about the list
                directly above it. */}
            {raw.trim().length > 0 && raw.trim().length < 2 ? (
              <p className="px-2 py-3 text-[12.5px] text-text-3">Keep typing, 2 characters minimum.</p>
            ) : raw.trim().length === 0 ? (
              <p className="px-2 py-3 text-[12.5px] text-text-3">
                {storeOnly ? 'Type to search the store.' : 'Type to search across the fleet.'}
              </p>
            ) : (query.length === 0 || (search.isFetching && flat.length === 0)) ? (
              sections.length === 0
                && <p className="px-2 py-3 text-[12.5px] text-text-3">Searching…</p>
            ) : flat.length === 0 ? (
              sections.length === 0
                && <p className="px-2 py-3 text-[12.5px] text-text-3">No results for &quot;{query}&quot;.</p>
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
