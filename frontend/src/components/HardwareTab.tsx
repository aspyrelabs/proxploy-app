import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import { fmtBytes } from '../lib/format'

/** GET /hosts/{id}/nodes/{node}/hardware. */
type Disk = {
  devpath: string
  model: string | null
  serial: string | null
  size: number | null
  type: string | null
  health: string | null
  wearout: number | null
  used: string | null
  osd_id: number | null
}

const card = 'rounded-card border border-line-soft bg-panel p-5'

export function HardwareTab({ hostId, node }: { hostId: number; node: string }) {
  const q = useQuery({
    queryKey: ['hosts', hostId, 'node', node, 'hardware'],
    queryFn: () => api<{ disks: Disk[] }>(`/hosts/${hostId}/nodes/${node}/hardware`),
    retry: false,
  })

  if (q.isError) {
    return (
      <section className={card}>
        <h2 className="mb-2 font-display text-[15px] font-semibold">Disks</h2>
        <p className="text-[13px] text-text-2">
          This node would not report its disks.
        </p>
        <p className="mt-1 text-[12px] text-text-3">
          Reading /nodes/{node}/disks/list needs Sys.Audit on the node. A token
          without it can still run everything else on this page.
        </p>
      </section>
    )
  }
  if (!q.data) return null

  return (
    <section className={card}>
      <h2 className="mb-3 font-display text-[15px] font-semibold">Disks</h2>
      {q.data.disks.length === 0 ? (
        <p className="text-[13px] text-text-2">This node reports no disks.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-[13px]">
            <thead>
              <tr className="text-[10.5px] uppercase tracking-wide text-text-3">
                <th className="pb-2 font-normal">Device</th>
                <th className="pb-2 font-normal">Model</th>
                <th className="pb-2 font-normal">Serial</th>
                <th className="pb-2 font-normal">Size</th>
                <th className="pb-2 font-normal">Type</th>
                <th className="pb-2 font-normal">Used by</th>
                <th className="pb-2 font-normal">Health</th>
                <th className="pb-2 font-normal">Wearout</th>
              </tr>
            </thead>
            <tbody>
              {q.data.disks.map((d) => (
                <tr key={d.devpath} className="border-t border-line-soft align-middle">
                  <td className="py-2 font-mono">{d.devpath}</td>
                  <td className="py-2 text-text-2">{d.model ?? 'unknown'}</td>
                  <td className="py-2 font-mono text-text-3">{d.serial ?? 'unknown'}</td>
                  <td className="py-2 font-mono">{d.size != null ? fmtBytes(d.size) : 'unknown'}</td>
                  <td className="py-2 text-text-2">{d.type ?? 'unknown'}</td>
                  <td className="py-2 text-text-2">
                    {d.osd_id != null ? `Ceph OSD ${d.osd_id}` : d.used ?? 'unknown'}
                  </td>
                  <td className={`py-2 ${d.health === 'PASSED' ? 'text-green' : 'text-amber'}`}>
                    {d.health ?? 'unknown'}
                  </td>
                  {/* PVE reports wearout as life REMAINING, not consumed. 99 is
                      a nearly-new disk, so labelling it "used" inverts it. */}
                  <td className="py-2 font-mono">
                    {d.wearout != null ? `${d.wearout}% left` : 'unknown'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
