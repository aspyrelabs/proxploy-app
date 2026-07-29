import { Link } from '@tanstack/react-router'
import { Brand } from './LoginForm'

export const NAV = [
  { label: 'Overview', items: [
    { label: 'Cluster', to: '/cluster' },
    { label: 'Apps', to: '/apps' },
    { label: 'App Store', to: '/store' },
    { label: 'Virtual Machines', to: '/vms' },
  ]},
  { label: 'Infrastructure', items: [
    { label: 'Storage', to: '/storage' },
    { label: 'Network', to: '/network' },
    { label: 'Backups', to: '/backups' },
    { label: 'Settings', to: '/settings' },
  ]},
] as const

export function SidebarNav() {
  return (
    <aside className="sticky top-0 flex h-screen w-[236px] shrink-0 flex-col border-r border-line-soft bg-panel/60 max-[720px]:hidden">
      <div className="px-4 py-4"><Brand /></div>
      <nav className="flex-1 overflow-y-auto px-2">
        {NAV.map(group => (
          <div key={group.label} className="mb-4">
            <div className="px-2 pb-1 text-[10.5px] font-semibold uppercase tracking-[.08em] text-text-3">{group.label}</div>
            {group.items.map(item => (
              // '/settings' lands in the route tree in Task 15; cast until then
              <Link key={item.to} to={item.to as never}
                className="relative block rounded-tile px-3 py-2 text-[13.5px] text-text-2 hover:bg-panel-2 hover:text-text"
                activeProps={{ className: 'bg-panel-2 !text-text before:absolute before:left-0 before:top-1.5 before:bottom-1.5 before:w-[3px] before:rounded before:bg-amber' }}>
                {item.label}
              </Link>
            ))}
          </div>
        ))}
      </nav>
      <div className="border-t border-line-soft px-4 py-3 text-[12px] text-text-2">
        <span className="mr-2 inline-block h-2 w-2 rounded-full bg-green shadow-[0_0_6px_rgba(63,207,142,.6)]" />
        All systems healthy
      </div>
    </aside>
  )
}
