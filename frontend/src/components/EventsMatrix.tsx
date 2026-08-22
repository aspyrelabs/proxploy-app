import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import { useEntitlements } from '../api/hooks'
import { useNotificationTypes, useSetNotificationTypes } from '../api/notificationTypes'
import type { TypeRow } from '../api/notificationTypes'
import type { ChannelRow } from './ChannelForm'

/**
 * What Proxploy tells you about, and where each thing goes.
 *
 * Rows are notification types, columns are a master switch followed by one per
 * configured channel. The master switch is the half that works with nothing
 * configured at all: off means you are never told, not even a toast, which is
 * what makes "the nightly housekeeping notification is annoying" a one-click
 * fix on an install that has no channels and does not want any.
 *
 * A cell is `notification_channels.events` transposed, which is why this
 * needed no migration. The one wrinkle is that an empty events list means
 * "every event" server-side: such a channel renders fully ticked, and the
 * first edit writes out the concrete list so it keeps receiving exactly what
 * it was receiving before, minus the box just cleared.
 */
export function EventsMatrix() {
  const qc = useQueryClient()
  const ent = useEntitlements()
  const types = useNotificationTypes()
  const setTypes = useSetNotificationTypes()

  // Same wait-for-first-fetch pattern as ChannelForm used to carry: has()
  // defaults to false until /entitlements resolves, so gating on it directly
  // would lock the columns for every plan during the initial fetch.
  const routingAllowed = ent.data == null || ent.has('notify.routing')

  const channels = useQuery({
    queryKey: ['notifications', 'channels'],
    queryFn: () => api<ChannelRow[]>('/notifications/channels'),
  })

  const setEvents = useMutation({
    mutationFn: ({ id, events }: { id: number; events: string[] }) =>
      api(`/notifications/channels/${id}`, {
        method: 'PATCH', body: JSON.stringify({ events }),
      }),
    onSettled: () => qc.invalidateQueries({ queryKey: ['notifications', 'channels'] }),
  })

  const rows = types.data?.rows ?? []
  const chans = channels.data ?? []

  /** Empty means every event, so read it as every key rather than none. */
  const ticked = (c: ChannelRow, key: string) =>
    c.events.length === 0 || c.events.includes(key)

  const toggleCell = (c: ChannelRow, key: string) => {
    // Materialise from what is currently ticked, not from c.events: for an
    // all-events channel those differ, and writing c.events back would
    // silently unsubscribe it from everything except the one box just touched.
    const current = rows.filter((r) => ticked(c, r.key)).map((r) => r.key)
    const next = ticked(c, key)
      ? current.filter((k) => k !== key)
      : [...current, key]
    setEvents.mutate({ id: c.id, events: next })
  }

  if (types.isPending) {
    return <p className="text-[12px] text-text-3">Loading notification types…</p>
  }

  const groups: string[] = []
  for (const r of rows) if (!groups.includes(r.group)) groups.push(r.group)

  return (
    <div className="space-y-3">
      {chans.length === 0 ? (
        <p className="text-[12px] text-text-3">
          Notifications are only shown in the app until you add a channel.
        </p>
      ) : !routingAllowed ? (
        <p className="text-[12px] text-text-3">
          On your plan, an enabled notification goes to every channel.
        </p>
      ) : null}

      <div className="overflow-x-auto">
        <table className="w-full text-[13px]">
          <thead>
            <tr className="text-left text-[11.5px] text-text-3">
              <th scope="col" className="py-1.5 pr-4">Notification</th>
              <th scope="col" className="py-1.5 pr-4">In app</th>
              {chans.map((c) => (
                <th key={c.id} scope="col" className="py-1.5 pr-4">{c.name}</th>
              ))}
            </tr>
          </thead>
          {groups.map((g) => (
            <tbody key={g}>
              <tr>
                <th scope="rowgroup" colSpan={2 + chans.length}
                    className="pt-4 pb-1 text-left text-[11.5px] uppercase tracking-wide text-text-3">
                  {g}
                </th>
              </tr>
              {rows.filter((r) => r.group === g).map((r: TypeRow) => (
                <tr key={r.key} className="border-t border-line">
                  <td className="py-1.5 pr-4 text-text-2">{r.label}</td>
                  <td className="py-1.5 pr-4">
                    <input type="checkbox" role="switch" aria-label={r.label}
                           checked={r.enabled} disabled={setTypes.isPending}
                           onChange={() => setTypes.mutate({ [r.key]: !r.enabled })} />
                  </td>
                  {chans.map((c) => (
                    <td key={c.id} className="py-1.5 pr-4">
                      <input type="checkbox"
                             aria-label={`Send ${r.label} to ${c.name}`}
                             checked={ticked(c, r.key)}
                             // A row that is off reaches nobody, so its
                             // columns would be describing something that
                             // cannot happen.
                             disabled={!r.enabled || !routingAllowed}
                             onChange={() => toggleCell(c, r.key)} />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          ))}
        </table>
      </div>
    </div>
  )
}
