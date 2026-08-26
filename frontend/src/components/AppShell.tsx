import { Outlet } from '@tanstack/react-router'
import { CommandPalette } from './CommandPalette'
import { NotificationSurface } from './NotificationSurface'
import { SidebarNav } from './SidebarNav'
import { Topbar } from './Topbar'

export function AppShell() {
  return (
    // Header spans full width so the brand mark sits top-left and never
    // collapses with the sidebar.
    <div className="min-h-screen">
      <Topbar />
      <div className="flex">
        <SidebarNav />
        <main className="min-w-0 flex-1 p-6"><Outlet /></main>
      </div>
      <CommandPalette />
      {/* No <Toaster> is mounted here any more. `sonner` stays a dependency
          only because HostPowerDialog.tsx, HostEditDialog.tsx and
          routes/hosts.tsx still call toast.success/error directly; those
          toasts render nothing until that migration lands. */}
      <NotificationSurface />
    </div>
  )
}
