import { Outlet } from '@tanstack/react-router'
import { Toaster } from 'sonner'
import { ActivityDrawer } from './ActivityDrawer'
import { ClearAllToasts } from './ClearAllToasts'
import { CommandPalette } from './CommandPalette'
import { SidebarNav } from './SidebarNav'
import { Topbar } from './Topbar'

export function AppShell() {
  return (
    // The header spans the full width and the sidebar starts beneath it, so the
    // brand mark sits in the top-left corner of the whole window rather than in
    // a column of its own. The previous shape — sidebar full height, header
    // only over the content — put the logo inside the pane that collapses,
    // which is the one place it should not move from.
    <div className="min-h-screen">
      <Topbar />
      <div className="flex">
        <SidebarNav />
        <main className="min-w-0 flex-1 p-6"><Outlet /></main>
      </div>
      <ActivityDrawer />
      <CommandPalette />
      <Toaster
        position="bottom-right"
        duration={2600}
        closeButton
        toastOptions={{
          className: 'rounded-ctl border border-line bg-panel-2 text-text text-[13px]',
        }}
      />
      <ClearAllToasts />
    </div>
  )
}
