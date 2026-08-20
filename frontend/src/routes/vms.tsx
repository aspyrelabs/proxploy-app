import { useQuery } from '@tanstack/react-query'
import { createRoute, useNavigate, useSearch } from '@tanstack/react-router'
import { useState } from 'react'
import { api } from '../api/client'
import type { VmRow } from '../api/hooks'
import { useEntitlements } from '../api/hooks'
import { QueryState } from '../components/QueryState'
import { SkeletonGroup } from '../components/ui/skeleton'
import { Button } from '../components/ui/button'
import { VmCreateWizard } from '../components/VmCreateWizard'
import { VmTable, VmTableSkeleton } from '../components/VmTable'

export function VmsPage() {
  const search = useSearch({ strict: false }) as { open?: number }
  const navigate = useNavigate()
  const ent = useEntitlements()
  const [creating, setCreating] = useState(false)
  const vmsQuery = useQuery({
    queryKey: ['vms', {}],
    queryFn: () => api<VmRow[]>('/vms'),
    refetchInterval: 30_000,
  })
  const vms = vmsQuery.data
  const running = vms?.filter((v) => v.status === 'running').length ?? 0
  // ent.has() is false until /entitlements resolves, gate on ent.data != null
  // too, or every plan sees a dead "New VM" button for the whole first fetch.
  const createDenied = ent.data != null && !ent.has('vms.create')
  return (
    <div>
      <div className="mb-5 flex items-center">
        <div>
          <h1 className="font-display text-[22px] font-semibold">Virtual Machines</h1>
          <div className="text-[12px] text-text-3">
            {vms ? `${vms.length} VMs · ${running} running` : '…'}
          </div>
        </div>
        <Button className="ml-auto" disabled={createDenied}
          title={createDenied ? 'Not included in your plan' : undefined}
          onClick={() => setCreating(true)}>
          New VM
        </Button>
      </div>
      <QueryState query={vmsQuery}
                  loading={<SkeletonGroup label="Loading virtual machines">
                    <VmTableSkeleton rows={6} />
                  </SkeletonGroup>}
                  emptyTitle="No VMs discovered"
                  emptyNote="QEMU guests on connected hosts are mirrored here by the poller."
                  errorTitle="VMs not readable"
                  errorNote="Proxploy could not reach the backend to list your VMs.">
        {/* Which row is expanded lives in the URL, so /vms?open=9 opens
            straight onto that VM the way its own page used to. */}
        {(rows) => <VmTable vms={rows} open={search.open}
                            onOpen={(open) => navigate({
                              to: '/vms' as never,
                              search: { ...search, open } as never,
                              replace: true,
                            })} />}
      </QueryState>
      {creating && <VmCreateWizard onClose={() => setCreating(false)} />}
    </div>
  )
}

// Route objects, imported by router.tsx (cluster.tsx precedent). shellRoute
// comes from ./shell, not ../router: importing router.tsx here would force
// its eager createRouter() to run mid-cycle when this file is the import
// entry point (e.g. in tests), before vmsRoute exists.
import { shellRoute } from './shell'

export const vmsRoute = createRoute({
  getParentRoute: () => shellRoute,
  path: '/vms',
  validateSearch: (s: Record<string, unknown>) => ({
    // The expanded row. Search params arrive as strings and VmTable compares
    // this against VmRow.id, which is a number.
    open: s.open != null ? Number(s.open) : undefined,
  }),
  component: VmsPage,
})
