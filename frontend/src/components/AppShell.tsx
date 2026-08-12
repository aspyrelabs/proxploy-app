import { Outlet } from '@tanstack/react-router'
import { CommandPalette } from './CommandPalette'
import { NotificationSurface } from './NotificationSurface'
import { SidebarNav } from './SidebarNav'
import { Topbar } from './Topbar'

export function AppShell() {
  return (
    // The header spans the full width and the sidebar starts beneath it, so the
    // brand mark sits in the top-left corner of the whole window rather than in
    // a column of its own. The previous shape (sidebar full height, header
    // only over the content) put the logo inside the pane that collapses,
    // which is the one place it should not move from.
    <div className="min-h-screen">
      <Topbar />
      <div className="flex">
        <SidebarNav />
        <main className="min-w-0 flex-1 p-6"><Outlet /></main>
      </div>
      <CommandPalette />
      {/* sonner's bottom-right <Toaster> and ClearAllToasts used to live
          here. There is one notification tray now, anchored to the topbar
          bell (BellPopover) with NotificationSurface as its brief
          under-the-bell preview -- nothing in the bottom corner any more.
          See .superpowers/sdd/one-notification-tray-report.md. The `sonner`
          package stays a dependency only because HostPowerDialog.tsx,
          HostEditDialog.tsx and routes/hosts.tsx still call its
          toast.success/error directly, mid-migration to notify.tsx by a
          separate change; their toasts render nothing until that migration
          lands, since nothing here mounts a <Toaster> for them any more. */}
      <NotificationSurface />
    </div>
  )
}
