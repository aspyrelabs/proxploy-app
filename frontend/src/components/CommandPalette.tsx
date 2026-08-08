import { useEffect, useRef, useState, useSyncExternalStore } from 'react'
import type { KeyboardEvent } from 'react'
import { useNavigate } from '@tanstack/react-router'
import { useEntitlements } from '../api/hooks'
import { useGlobalSearch } from '../api/search'
import type { SearchResult } from '../api/search'

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

function rowId(r: SearchResult): string {
  return `cmdk-${r.kind}-${r.id}`
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
  const [selIndex, setSelIndex] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)
  const restoreFocus = useRef<HTMLElement | null>(null)

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

  useEffect(() => { setSelIndex(0) }, [search.data])

  useEffect(() => {
    if (!open) { restoreFocus.current?.focus(); return }
    restoreFocus.current = document.activeElement as HTMLElement | null
    setRaw('')
    setQuery('')
    setSelIndex(0)
    const t = setTimeout(() => inputRef.current?.focus(), 0)
    return () => clearTimeout(t)
  }, [open])

  // The only global keydown listener in the app: registered once for the
  // component's whole (app-length) lifetime and cleaned up on unmount.
  // `paletteOpen` is read live (not via a stale `open` closure) so this
  // never needs re-registering as the palette opens and closes.
  useEffect(() => {
    function onKeyDown(e: globalThis.KeyboardEvent): void {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        // A dead shortcut is worse than a locked one: this opens even for a
        // viewer without ui.global_search, the dialog itself shows the plan
        // message instead of doing nothing.
        setPaletteOpen(true)
      } else if (e.key === 'Escape' && paletteOpen) {
        setPaletteOpen(false)
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

  const onInputKeyDown = (e: KeyboardEvent<HTMLInputElement>): void => {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setSelIndex((i) => Math.min(i + 1, flat.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setSelIndex((i) => Math.max(i - 1, 0))
    } else if (e.key === 'Enter') {
      e.preventDefault()
      const r = flat[selIndex]
      if (r) go(r)
    }
  }

  const active = flat[selIndex]

  return (
    <div role="dialog" aria-modal="true" aria-label="Search"
         className="fixed inset-0 z-30 grid place-items-start justify-center bg-scrim pt-[12vh] backdrop-blur-[3px]"
         onClick={close}>
      <div className="w-[560px] max-w-[92vw] rounded-card border border-line bg-panel p-3"
           onClick={(e) => e.stopPropagation()}>
        <input
          ref={inputRef}
          role="combobox"
          aria-label="Search apps, VMs, hosts and the store"
          aria-expanded={flat.length > 0}
          aria-controls="cmdk-listbox"
          aria-activedescendant={active ? rowId(active) : undefined}
          disabled={denied}
          title={denied ? 'Not included in your plan' : undefined}
          className="w-full rounded-ctl border border-line bg-panel-2 px-3 py-2 text-[14px] text-text outline-none disabled:opacity-60"
          placeholder="Search apps, VMs, hosts, the store…"
          value={raw}
          onChange={(e) => setRaw(e.target.value)}
          onKeyDown={onInputKeyDown}
        />

        {denied ? (
          <p className="mt-3 px-1 text-[12.5px] text-text-3">
            Global search is not included in your plan. Upgrade to search apps, VMs, hosts and
            the store from anywhere.
          </p>
        ) : (
          <div id="cmdk-listbox" role="listbox" aria-label="Search results"
               className="mt-2 max-h-[50vh] overflow-auto">
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
                <div key={g.kind} className="mb-1">
                  <div className="px-2 py-1 text-[11px] uppercase tracking-wide text-text-3">{g.label}</div>
                  {g.items.map((r) => {
                    const selected = active != null && rowId(active) === rowId(r)
                    return (
                      <div key={rowId(r)} id={rowId(r)} role="option" aria-selected={selected}
                        className={`flex cursor-pointer items-center justify-between rounded-ctl px-2 py-1.5 text-[13px] ${
                          selected ? 'bg-elev text-text' : 'text-text-2 hover:bg-panel-2'}`}
                        onMouseEnter={() => setSelIndex(flat.indexOf(r))}
                        onClick={() => go(r)}>
                        <span>
                          {r.label}
                          {r.sublabel && <span className="ml-2 text-[11.5px] text-text-3">{r.sublabel}</span>}
                        </span>
                        {r.status && <span className="text-[11px] text-text-3">{r.status}</span>}
                      </div>
                    )
                  })}
                </div>
              ))
            )}
          </div>
        )}
      </div>
    </div>
  )
}
