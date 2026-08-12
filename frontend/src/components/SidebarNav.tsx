import { Link } from '@tanstack/react-router'
import {
  ArchiveBoxIcon, BellAlertIcon, CircleStackIcon, ClipboardDocumentListIcon,
  Cog6ToothIcon, ComputerDesktopIcon, GlobeAltIcon, ServerStackIcon,
  ShoppingBagIcon, Squares2X2Icon,
} from '@heroicons/react/24/outline'
import { HealthFooter } from './HealthFooter'

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
  return (
    <aside className="sticky top-0 flex h-screen w-[236px] shrink-0 flex-col border-r border-line-soft bg-panel/60 max-[720px]:hidden">
      <nav className="flex-1 overflow-y-auto px-2">
        {NAV.map(group => (
          <div key={group.label} className="mb-4">
            <div className="px-2 pb-1 text-[10.5px] font-semibold uppercase tracking-[.08em] text-text-3">{group.label}</div>
            {group.items.map(item => (
              // cast: circular router-tree imports across route files defeat
              // full inference of the nav's `to` union in this TS/router version
              <Link key={item.to} to={item.to as never}
                className="relative flex items-center gap-3 rounded-tile px-3 py-2 text-[13.5px] text-text-2 hover:bg-panel-2 hover:text-text"
                activeProps={{ className: 'bg-panel-2 !text-text before:absolute before:left-0 before:top-1.5 before:bottom-1.5 before:w-[3px] before:rounded before:bg-amber' }}>
                <item.icon aria-hidden className="h-[18px] w-[18px] shrink-0" />
                {item.label}
              </Link>
            ))}
          </div>
        ))}
      </nav>
      <HealthFooter />
    </aside>
  )
}
