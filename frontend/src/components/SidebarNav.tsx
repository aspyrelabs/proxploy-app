import { useState } from 'react'
import { Link } from '@tanstack/react-router'
import * as Tooltip from '@radix-ui/react-tooltip'
import { Icon } from './ui/icon'
import { HealthFooter } from './HealthFooter'
import { readSidebarCollapsed, setSidebarCollapsed } from '../lib/sidebar'

// `icon` is a Material Symbols name (see components/ui/icon.tsx), not a
// component reference -- these ten are a deliberate, fixed set of concepts
// (see nav.test.tsx) and each name below is verified against the real font
// in the material-symbols report, not guessed.
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
    { label: 'Backups', to: '/backups', icon: 'archive' },
    { label: 'Alerts', to: '/alerts', icon: 'notifications_active' },
    { label: 'Audit', to: '/audit', icon: 'fact_check' },
    { label: 'Settings', to: '/settings', icon: 'settings' },
  ]},
] as const

export function SidebarNav() {
  const [collapsed, setCollapsed] = useState(readSidebarCollapsed)
  const toggle = () => {
    const next = !collapsed
    setSidebarCollapsed(next)
    setCollapsed(next)
  }
  return (
    <Tooltip.Provider delayDuration={200}>
      {/* top-14 / 100vh-3.5rem, not top-0 / h-screen: the header is now above
          this pane rather than beside it, so the pane starts under the header
          and its height is the window minus that bar. */}
      <aside className={`sticky top-14 flex h-[calc(100vh-3.5rem)] shrink-0 flex-col border-r border-line-soft bg-panel/60 transition-[width] duration-200 motion-reduce:transition-none max-[720px]:hidden ${collapsed ? 'w-16' : 'w-[236px]'}`}>
        <nav className="flex-1 overflow-y-auto px-2 pt-2">
          {NAV.map((group) => (
            <div key={group.label} className="mb-4">
              {collapsed
                // The heading's job is to separate the two groups. With no
                // room for the word, a rule does that job and the word does
                // not fit; keeping it truncated would be worse than a line.
                ? <div className="mx-2 mb-2 border-t border-line-soft" />
                : <div className="px-2 pb-1 text-[10.5px] font-semibold uppercase tracking-[.08em] text-text-3">{group.label}</div>}
              {group.items.map((item) => (
                <NavItem key={item.to} item={item} collapsed={collapsed} />
              ))}
            </div>
          ))}
        </nav>
        <HealthFooter collapsed={collapsed} />
        {/* Last, under the health line. It is chrome for the sidebar itself
            rather than a destination, so it sits out of the way of the nav
            instead of above it, and it is the only thing down here that is
            always present: the health footer renders nothing while nothing is
            wrong, so the rail must not depend on it for its bottom edge.
            py-[3px], not py-2.5: the button is a 32px hit target holding an 18px
            glyph, so it already carries 7px around it. 10px of row padding on
            top of that put 17px around the chevron. 3 + 7 gives the glyph its
            10px while the button stays big enough to hit. */}
        <div className={`flex border-t border-line-soft px-2 py-[3px] ${collapsed ? 'justify-center' : 'justify-end'}`}>
          <button type="button" onClick={toggle}
            aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            className="grid h-8 w-8 place-items-center rounded-tile text-text-3 hover:bg-panel-2 hover:text-text">
            <Icon name={collapsed ? 'keyboard_double_arrow_right' : 'keyboard_double_arrow_left'} />
          </button>
        </div>
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
      {/* 22 rather than the 18 default: these ten are the app's primary
          navigation, and they carry the whole meaning of the rail once it is
          collapsed to icons only. The collapse chevron beside them stays at 18,
          since it is a control rather than a destination and its row height is
          tuned to 38px. */}
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
