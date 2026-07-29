import { Outlet } from '@tanstack/react-router'
import { SidebarNav } from './SidebarNav'
import { Topbar } from './Topbar'

export function AppShell() {
  return (
    <div className="flex min-h-screen">
      <SidebarNav />
      <div className="min-w-0 flex-1">
        <Topbar />
        <main className="p-6"><Outlet /></main>
      </div>
    </div>
  )
}
