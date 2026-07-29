import { Outlet } from '@tanstack/react-router'
import { Toaster } from 'sonner'
import { SidebarNav } from './SidebarNav'
import { Topbar } from './Topbar'

// ActivityDrawer lands in Task 10 — its import and element are added there,
// not here, so this task builds on its own (controller ruling, task-9 brief).
export function AppShell() {
  return (
    <div className="flex min-h-screen">
      <SidebarNav />
      <div className="min-w-0 flex-1">
        <Topbar />
        <main className="p-6"><Outlet /></main>
      </div>
      <Toaster
        position="bottom-right"
        duration={2600}
        toastOptions={{
          className: 'rounded-ctl border border-line bg-panel-2 text-text text-[13px]',
        }}
      />
    </div>
  )
}
