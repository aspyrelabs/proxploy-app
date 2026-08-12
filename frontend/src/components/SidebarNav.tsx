import { useState } from 'react'
import { Link } from '@tanstack/react-router'
import * as Tooltip from '@radix-ui/react-tooltip'
import {
  ArchiveBoxIcon, BellAlertIcon, ChevronDoubleLeftIcon, ChevronDoubleRightIcon,
  CircleStackIcon, ClipboardDocumentListIcon, Cog6ToothIcon, ComputerDesktopIcon,
  GlobeAltIcon, ServerStackIcon, ShoppingBagIcon, Squares2X2Icon,
} from '@heroicons/react/24/outline'
import { HealthFooter } from './HealthFooter'
import { readSidebarCollapsed, setSidebarCollapsed } from '../lib/sidebar'

export const NAV = [
  { label: 'Overview', items: [
    { label: 'Hosts', to: '/hosts', icon: ServerStackIcon },
    { label: 'Apps', to: '/apps', icon: Squares2X2Icon },
    { label: 'App Store', to: '/store', icon: ShoppingBagIcon },
    { label: 'Virtual Machines', to: '/vms', icon: ComputerDesktopIcon },
  ]},
  { label: 'Infrastructure', items: [
    { label: 'Storage', to: '/storage', icon: CircleStackIcon },
    { label: 'Network', to: '/network', icon: GlobeAltIcon },
    { label: 'Backups', to: '/backups', icon: ArchiveBoxIcon },
    { label: 'Alerts', to: '/alerts', icon: BellAlertIcon },
    { label: 'Audit', to: '/audit', icon: ClipboardDocumentListIcon },
    { label: 'Settings', to: '/settings', icon: Cog6ToothIcon },
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
        <div className={`flex px-2 py-3 ${collapsed ? 'justify-center' : 'justify-end'}`}>
          <button type="button" onClick={toggle}
            aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            className="grid h-8 w-8 place-items-center rounded-tile text-text-3 hover:bg-panel-2 hover:text-text">
            {collapsed
              ? <ChevronDoubleRightIcon aria-hidden className="h-[18px] w-[18px]" />
              : <ChevronDoubleLeftIcon aria-hidden className="h-[18px] w-[18px]" />}
          </button>
        </div>
        <nav className="flex-1 overflow-y-auto px-2">
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
      <item.icon aria-hidden className="h-[18px] w-[18px] shrink-0" />
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
