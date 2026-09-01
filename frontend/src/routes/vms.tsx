import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { createRoute, useNavigate, useSearch } from '@tanstack/react-router'
import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { VmRow } from '../api/hooks'
import { useEntitlements } from '../api/hooks'
import { QueryState } from '../components/QueryState'
import { SkeletonGroup } from '../components/ui/skeleton'
import { Loading } from '../components/ui/loading'
import { Button, segment } from '../components/ui/button'
import { VmCreateWizard } from '../components/VmCreateWizard'
import { VmTable, VmTableSkeleton } from '../components/VmTable'
import { TableSorter, useSorted } from '../components/TableSorter'

const PENDING_POLL_MS = 2_000
const PENDING_TIMEOUT_MS = 30_000
const IDLE_POLL_MS = 30_000

type HostRow = { id: number; name: string }

const inputCls = 'rounded-ctl border border-line bg-panel px-3 py-1.5 text-[13px] text-text placeholder:text-text-3 focus:outline-none focus:ring-1 focus:ring-amber'

export function VmsPage() {
  const search = useSearch({ strict: false }) as { host?: number; q?: string; open?: number }
  const navigate = useNavigate()
  const ent = useEntitlements()
  const [creating, setCreating] = useState(false)
  const [pending, setPending] = useState<{ vmid: number; timedOut: boolean } | null>(null)
  const hostsQuery = useQuery({
    queryKey: ['hosts'],
    queryFn: () => api<HostRow[]>('/hosts'),
  })
  const hosts = hostsQuery.data
  const vmsQuery = useQuery({
    placeholderData: keepPreviousData,
    queryKey: ['vms', { host: search.host }],
    queryFn: () => api<VmRow[]>(
      search.host != null ? `/vms?host=${search.host}` : '/vms'),
    refetchInterval: (query) => {
      if (!pending || pending.timedOut) return IDLE_POLL_MS
      const found = query.state.data?.some((v) => v.vmid === pending.vmid)
      return found ? IDLE_POLL_MS : PENDING_POLL_MS
    },
  })

  useEffect(() => {
    if (pending && !pending.timedOut && vmsQuery.data?.some((v) => v.vmid === pending.vmid)) {
      setPending(null)
    }
  }, [pending, vmsQuery.data])

  useEffect(() => {
    if (!pending || pending.timedOut) return
    const t = setTimeout(() => setPending((p) => (p ? { ...p, timedOut: true } : p)), PENDING_TIMEOUT_MS)
    return () => clearTimeout(t)
  }, [pending])
  const needle = (search.q ?? '').trim().toLowerCase()
  const vms = needle
    ? vmsQuery.data?.filter((v) =>
        v.name.toLowerCase().includes(needle)
        || String(v.vmid).includes(needle)
        || v.host_name.toLowerCase().includes(needle))
    : vmsQuery.data
  const running = vms?.filter((v) => v.status === 'running').length ?? 0

  const setSearch = (patch: Partial<{ host?: number; q?: string; open?: number }>) =>
    navigate({ to: '/vms' as never, search: { ...search, ...patch } as never, replace: true })
  // Client-side, on rows the query already holds (usePaged precedent on
  // /backups). Not in the URL beside `open`: that names a VM someone can be
  // sent to, this is only which order the rows are stacked in.
  const sorted = useSorted(vms ?? [])
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
        <div className="ml-auto flex items-center gap-3">
          <Button disabled={createDenied}
            title={createDenied ? 'Not included in your plan' : undefined}
            onClick={() => setCreating(true)}>
            New VM
          </Button>
        </div>
      </div>
      <div className="mb-4 flex items-center gap-3">
        <div className="flex overflow-hidden rounded-ctl border border-line">
          <button
            className={`px-3 py-1.5 text-[12px] ${segment(search.host == null)}`}
            onClick={() => setSearch({ host: undefined })}
          >
            All hosts
          </button>
          {(hosts ?? []).map((h) => (
            <button
              key={h.id}
              className={`border-l border-line px-3 py-1.5 text-[12px] ${segment(search.host === h.id)}`}
              onClick={() => setSearch({ host: h.id })}
            >
              {h.name}
            </button>
          ))}
          {hostsQuery.isError && (
            <span className="border-l border-line px-3 py-1.5 text-[12px] text-red">
              Could not load hosts
            </span>
          )}
        </div>
        <input
          className={inputCls}
          placeholder="Filter virtual machines…"
          defaultValue={search.q ?? ''}
          onChange={(e) => setSearch({ q: e.target.value || undefined })}
        />
        <span className="rounded-full bg-panel-2 px-2 py-0.5 font-mono text-[11px] text-text-2">
          {vms?.length ?? 0} shown
        </span>
        <div className="ml-auto">
          <TableSorter sort={sorted.sort} onSort={sorted.setSort}
                       label="virtual machines" />
        </div>
      </div>
      {pending && !pending.timedOut && (
        <div className="mb-4 flex items-center gap-2 rounded-ctl border border-line-soft bg-elev p-2 text-[12.5px] text-text-2">
          <Loading label="Creating the VM" size={16} />
          Creating VM {pending.vmid}. It can take up to 30 seconds to show up here.
        </div>
      )}
      {pending && pending.timedOut && (
        <p role="alert"
           className="mb-4 rounded-ctl border border-amber/30 bg-amber-dim p-2 text-[12.5px] text-text-2">
          VM {pending.vmid} has not shown up yet. Check Activity, the bell icon at the top,
          to see what happened to the job.
        </p>
      )}
      <QueryState query={vmsQuery}
                  loading={<SkeletonGroup label="Loading virtual machines">
                    <VmTableSkeleton rows={6} />
                  </SkeletonGroup>}
                  emptyTitle="No VMs discovered"
                  emptyNote="QEMU guests on connected hosts are mirrored here by the poller."
                  errorTitle="VMs not readable"
                  errorNote="Proxploy could not reach the backend to list your VMs.">
        {/* `open` lives in the URL so /vms?open=9 deep-links onto that VM.
            Pass the sorted rows, not the raw ones: QueryState still owns
            loading/error/empty, just not the order. */}
        {() => sorted.rows.length === 0 ? (
          <p className="text-[12.5px] text-text-3">
            No virtual machines match your filter.
          </p>
        ) : (
          <VmTable vms={sorted.rows} open={search.open}
                   onOpen={(open) => navigate({
                     to: '/vms' as never,
                     search: { ...search, open } as never,
                     replace: true,
                   })} />
        )}
      </QueryState>
      {creating && <VmCreateWizard onClose={(vmid) => {
        setCreating(false)
        if (vmid != null) setPending({ vmid, timedOut: false })
      }} />}
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
