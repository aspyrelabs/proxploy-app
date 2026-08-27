import { useEffect, useState } from 'react'
import { Link } from '@tanstack/react-router'
import * as Tooltip from '@radix-ui/react-tooltip'
import { Icon } from './ui/icon'
import { readSidebarCollapsed, setSidebarCollapsed } from '../lib/sidebar'

// `icon` is a Material Symbols name (see components/ui/icon.tsx), not a
// component reference. Each name below is verified against the real font in
// the material-symbols report, not guessed.
export const NAV = [
  { label: 'Overview', items: [
    { label: 'Hosts', to: '/hosts', icon: 'dns' },
    { label: 'Apps', to: '/apps', icon: 'grid_view' },
    { label: 'App Store', to: '/store', icon: 'storefront' },
    { label: 'Virtual Machines', to: '/vms', icon: 'computer' },
  ]},
  { label: 'Infrastructure', items: [
    { label: 'Storage', to: '/storage', icon: 'database' },
    { label: 'Network', to: '/network', icon: 'public' },
    { label: 'Firewall', to: '/firewall', icon: 'shield' },
    { label: 'Backups', to: '/backups', icon: 'archive' },
    { label: 'Alerts', to: '/alerts', icon: 'notifications_active' },
    { label: 'Audit', to: '/audit', icon: 'fact_check' },
    { label: 'Settings', to: '/settings', icon: 'settings' },
  ]},
] as const

const NARROW = '(max-width: 1439px)'

export function SidebarNav() {
  const [chosen, setChosen] = useState(readSidebarCollapsed)
  const [narrow, setNarrow] = useState(
    () => typeof window !== 'undefined' && window.matchMedia(NARROW).matches)
  useEffect(() => {
    const mq = window.matchMedia(NARROW)
    const on = () => setNarrow(mq.matches)
    on()
    mq.addEventListener('change', on)
    return () => mq.removeEventListener('change', on)
  }, [])
  const collapsed = chosen || narrow
  const toggle = () => {
    const next = !collapsed
    setSidebarCollapsed(next)
    setChosen(next)
  }
  return (
    <Tooltip.Provider delayDuration={200}>
      {/* top-14 / 100vh-3.5rem, not top-0 / h-screen: the header sits above
          this pane, so it starts under the header and its height is the
          window minus that bar. */}
      <aside className={`sticky top-14 flex h-[calc(100vh-3.5rem)] shrink-0 flex-col border-r border-line-soft bg-panel/60 transition-[width] duration-200 motion-reduce:transition-none max-[720px]:hidden ${collapsed ? 'w-16' : 'w-[236px]'}`}>
        <nav className="flex-1 overflow-y-auto px-2 pt-2">
          {NAV.map((group) => (
            <div key={group.label} className="mb-4">
              {collapsed
                // Collapsed: a divider separates the two groups better than a
                // truncated heading.
                ? <div className="mx-2 mb-2 border-t border-line-soft" />
                : <div className="px-2 pb-1 text-[10.5px] font-semibold uppercase tracking-[.08em] text-text-3">{group.label}</div>}
              {group.items.map((item) => (
                <NavItem key={item.to} item={item} collapsed={collapsed} />
              ))}
            </div>
          ))}
        </nav>
        {/* Chrome for the sidebar itself, not a destination, so it sits out of
            the way of the nav. The sidebar reports no status of its own; the
            pages that own each subject report it.
            py-[3px], not py-2.5: the 32px hit target holds an 18px glyph
            (7px around it), so 3px more gives the glyph 10px and keeps the
            button big enough to hit. */}
        {!narrow && (
          <div className={`flex border-t border-line-soft px-2 py-[3px] ${collapsed ? 'justify-center' : 'justify-end'}`}>
            <button type="button" onClick={toggle}
              aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
              className="grid h-8 w-8 place-items-center rounded-tile text-text-3 hover:bg-panel-2 hover:text-text">
              <Icon name={collapsed ? 'keyboard_double_arrow_right' : 'keyboard_double_arrow_left'} />
            </button>
          </div>
        )}
      </aside>
    </Tooltip.Provider>
  )
}

function NavItem({ item, collapsed }: {
  item: (typeof NAV)[number]['items'][number]
  collapsed: boolean
}) {
  const link = (
    // cast: circular router-tree imports across route files defeat
    // full inference of the nav's `to` union in this TS/router version
    <Link to={item.to as never}
      // aria-label only when collapsed: with the text visible it would
      // override the label the user can actually read, and the two must not
      // drift apart.
      aria-label={collapsed ? item.label : undefined}
      className={`relative flex items-center gap-3 rounded-tile py-2 text-[13.5px] text-text-2 hover:bg-panel-2 hover:text-text ${collapsed ? 'justify-center px-0' : 'px-3'}`}
      activeProps={{ className: 'bg-panel-2 !text-text before:absolute before:left-0 before:top-1.5 before:bottom-1.5 before:w-[3px] before:rounded before:bg-amber' }}>
      {/* 22, not the 18 default: these icons carry the whole meaning of the
          rail once collapsed to icons only. The chevron beside them stays at
          18 -- it is a control, not a destination. */}
      <Icon name={item.icon} size={22} className="shrink-0" />
      {!collapsed && item.label}
    </Link>
  )
  if (!collapsed) return link
  return (
    <Tooltip.Root>
      <Tooltip.Trigger asChild>{link}</Tooltip.Trigger>
      <Tooltip.Portal>
        <Tooltip.Content side="right" sideOffset={6}
          className="z-50 rounded-tile border border-line bg-elev px-2 py-1 text-[12px] text-text shadow-lg">
          {item.label}
        </Tooltip.Content>
      </Tooltip.Portal>
    </Tooltip.Root>
  )
}
