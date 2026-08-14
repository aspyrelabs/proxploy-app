import { useState } from 'react'
import * as Tabs from '@radix-ui/react-tabs'
import { createRoute } from '@tanstack/react-router'
import { useDeleteVolume, useStorage, useStorageContent, useStorageDetail } from '../api/storage'
import type { StorageRow, VolumeRow } from '../api/storage'
import { EmptyState } from '../components/EmptyState'
import { KVGrid } from '../components/KVGrid'
import { QueryState } from '../components/QueryState'
import { SkeletonGroup } from '../components/ui/skeleton'
import { StorageCard, StorageCardSkeleton } from '../components/StorageCard'
import { StorageForm } from '../components/StorageForm'
import { UploadDialog } from '../components/UploadDialog'
import { Button } from '../components/ui/button'
import { fmtBytes } from '../lib/format'
// shellRoute comes from ./shell, never ../router; importing router.tsx here
// would force its eager createRouter() to run mid-cycle (cluster.tsx carries
// the same note).
import { shellRoute } from './shell'

const card = 'rounded-card border border-line-soft bg-panel p-5'
// Hoisted so the loading placeholder lays out in the SAME grid as the cards it
// stands in for. Two copies of the string is one copy too many.
const STORAGE_GRID = 'grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3'

// PVE's content classes, in the order the browser shows them. The tab strip is
// filtered against the datastore's own advertised `content` list, so a PBS
// datastore offers Backups only and a dir storage offers all four.
const CONTENT_TABS = [
  { key: 'iso', label: 'ISOs' },
  { key: 'vztmpl', label: 'Templates' },
  { key: 'backup', label: 'Backups' },
  { key: 'images', label: 'Disk images' },
] as const

function fmtCtime(ctime: number | null) {
  return ctime == null ? 'unknown' : new Date(ctime * 1000).toLocaleString()
}

function VolumeTable({ volumes, hostId, node, storage }:
  { volumes: VolumeRow[]; hostId: number; node: string; storage: string }) {
  const del = useDeleteVolume()
  if (volumes.length === 0) {
    return <EmptyState title="Nothing stored here yet" note="Volumes of this content type appear here." />
  }
  return (
    <table className="w-full text-left text-[13px]">
      <thead>
        <tr className="text-[11px] uppercase text-text-3">
          <th scope="col" className="pb-2 font-medium">Volume</th>
          <th scope="col" className="pb-2 font-medium">Format</th>
          <th scope="col" className="pb-2 font-medium">Size</th>
          <th scope="col" className="pb-2 font-medium">Guest</th>
          <th scope="col" className="pb-2 font-medium">Created</th>
          <th scope="col" className="pb-2 font-medium">Delete</th>
        </tr>
      </thead>
      <tbody>
        {volumes.map((v) => (
          <tr key={v.volid} className="border-t border-line-soft hover:bg-panel-2">
            <td className="py-2.5 font-mono">{v.volid}</td>
            <td className="py-2.5 font-mono text-text-2">{v.format ?? 'unknown'}</td>
            <td className="py-2.5 font-mono text-text-2">{fmtBytes(v.size)}</td>
            <td className="py-2.5 font-mono text-text-2">{v.vmid ?? 'unknown'}</td>
            <td className="py-2.5 font-mono text-text-2">{fmtCtime(v.ctime)}</td>
            <td className="py-2.5" onClick={(e) => e.stopPropagation()}>
              <Button
                variant="danger"
                className="px-2 py-1 text-[11px]"
                disabled={del.isPending}
                onClick={() => {
                  if (window.confirm(`Delete ${v.volid}? This removes the volume from ${storage} and cannot be undone.`)) {
                    del.mutate({ hostId, storage, node, volid: v.volid })
                  }
                }}
              >
                Delete
              </Button>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

export function ContentBrowser({ row, onClose, onManage }:
  { row: StorageRow; onClose: () => void; onManage: (row: StorageRow) => void }) {
  const [uploading, setUploading] = useState(false)
  const tabs = CONTENT_TABS.filter((t) => row.content.includes(t.key))
  const [active, setActive] = useState<string>(tabs[0]?.key ?? 'iso')
  const detail = useStorageDetail(row.host_id, row.storage)
  const { data: volumes, isError } = useStorageContent(row.host_id, row.storage, active)

  return (
    <div className={`${card} mt-5`}>
      <div className="mb-4 flex items-start justify-between">
        <div>
          <h2 className="font-mono text-[16px] font-semibold">{row.storage}</h2>
          <div className="font-mono text-[11px] text-text-3">
            {row.host_name} · {row.node} · {row.type ?? 'unknown'}
            {row.shared ? ' · shared' : ''}
          </div>
        </div>
        <div className="flex gap-2">
          <Button variant="ghost" className="px-2 py-1 text-[11px]"
            onClick={() => setUploading(true)}>Upload</Button>
          <Button variant="ghost" className="px-2 py-1 text-[11px]"
            onClick={() => onManage(row)}>Manage</Button>
          <Button variant="ghost" className="px-2 py-1 text-[11px]" onClick={onClose}>Close</Button>
        </div>
      </div>

      {uploading && (
        <UploadDialog hostId={row.host_id} storage={row.storage} node={row.node}
          contentTypes={row.content} onClose={() => setUploading(false)} />
      )}

      <KVGrid items={[
        ['Status', row.status],
        ['Used', fmtBytes(row.used_bytes)],
        ['Free', fmtBytes(detail.data?.avail_bytes)],
        ['Total', fmtBytes(row.total_bytes)],
        ['Nodes', (detail.data?.nodes ?? [row.node]).join(', ')],
        ['Content', row.content.join(', ') || '; '],
      ]} />

      {/* Radix Tabs, not router child-routes: this strip only filters the list
          below it and was never deep-linkable. The tab strips on the apps, host
          and VM pages ARE child routes and stay that way, because converting
          them would break links like ?tab=logs. */}
      <Tabs.Root value={active} onValueChange={(v) => setActive(v as typeof active)}>
        <Tabs.List className="mb-4 mt-5 flex gap-1 border-b border-line-soft">
          {tabs.map((t) => (
            <Tabs.Trigger
              key={t.key}
              value={t.key}
              className="cursor-pointer px-3 py-2 text-[13px] text-text-2 hover:text-text
                         data-[state=active]:border-b-2 data-[state=active]:border-amber
                         data-[state=active]:text-text"
            >
              {t.label}
            </Tabs.Trigger>
          ))}
        </Tabs.List>

        {tabs.map((t) => (
          <Tabs.Content key={t.key} value={t.key}>
            {isError ? (
              <EmptyState title="Content listing unavailable"
                note="Proxploy could not reach this datastore; it may be offline or the node may be down." />
            ) : (
              <VolumeTable volumes={volumes ?? []} hostId={row.host_id} node={row.node} storage={row.storage} />
            )}
          </Tabs.Content>
        ))}
      </Tabs.Root>
    </div>
  )
}

export function StoragePage() {
  const storageQuery = useStorage()
  const rows = storageQuery.data
  const [open, setOpen] = useState<StorageRow | null>(null)
  // 'new' = attach, a row = edit + detach. One dialog, two modes; a second
  // component would be the same form with two fields locked.
  const [form, setForm] = useState<'new' | StorageRow | null>(null)

  return (
    <div>
      <div className="mb-5 flex items-center justify-between">
        <div>
          <h1 className="font-display text-[22px] font-semibold">Storage</h1>
          <div className="text-[12px] text-text-3">
            {rows ? `${rows.length} datastores across the cluster` : '…'}
          </div>
        </div>
        <Button variant="primary" onClick={() => setForm('new')}>Add storage</Button>
      </div>

      <QueryState query={storageQuery}
                  loading={<SkeletonGroup label="Loading datastores" className={STORAGE_GRID}>
                    {Array.from({ length: 6 }, (_, i) => <StorageCardSkeleton key={i} />)}
                  </SkeletonGroup>}
                  emptyTitle="No datastores yet"
                  emptyNote="Datastores on connected Proxmox hosts appear here after the first poll."
                  errorTitle="Datastores not readable"
                  errorNote="Proxploy could not reach the backend to list your datastores.">
        {(list) => (
          <div className={STORAGE_GRID}>
            {list.map((r) => (
              <StorageCard key={`${r.host_id}:${r.node}:${r.storage}`} row={r} onOpen={setOpen} />
            ))}
          </div>
        )}
      </QueryState>

      {open && (
        // Keyed so switching datastores resets the content tab and the two
        // queries, rather than showing the previous datastore's volumes for a
        // frame while the new ones load.
        <ContentBrowser key={`${open.host_id}:${open.storage}`} row={open}
          onClose={() => setOpen(null)} onManage={setForm} />
      )}

      {form && (
        <StorageForm existing={form === 'new' ? null : form}
          onClose={() => setForm(null)} />
      )}
    </div>
  )
}

export const storageRoute = createRoute({
  getParentRoute: () => shellRoute,
  path: '/storage',
  component: StoragePage,
})
