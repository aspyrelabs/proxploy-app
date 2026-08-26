import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import { useEntitlements } from '../api/hooks'
import { useNotificationTypes, useSetNotificationTypes } from '../api/notificationTypes'
import type { TypeRow } from '../api/notificationTypes'
import type { ChannelRow } from './ChannelForm'
import { Skeleton, SkeletonGroup } from './ui/skeleton'
import { Switch } from './ui/switch'
import { PublicUrlField } from './PublicUrlField'

/**
 * Rows are notification types; columns are a master switch then one per
 * channel. A cell transposes `notification_channels.events` (hence no
 * migration). An empty events list means "every event" server-side: such a
 * channel renders fully ticked, and the first edit writes out the concrete
 * list so it keeps receiving exactly what it was.
 */
export function EventsMatrix() {
  const qc = useQueryClient()
  const ent = useEntitlements()
  const types = useNotificationTypes()
  const setTypes = useSetNotificationTypes()

  // Wait for first fetch: has() defaults false until /entitlements resolves,
  // so gating on it directly would lock the columns for every plan on load.
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
    // Skeleton group: a single text line under-describes nineteen rows and
    // the section would jump when they land.
    return (
      <SkeletonGroup label="Loading notification types" className="space-y-2">
        <Skeleton className="h-[14px] w-40" />
        {Array.from({ length: 10 }, (_, i) => (
          <div key={i} className="flex items-center gap-4">
            <Skeleton className="h-[14px] flex-1" />
            <Skeleton className="h-[14px] w-8" />
          </div>
        ))}
      </SkeletonGroup>
    )
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
        {/* w-auto, not w-full: stretched to the card, the label column
            absorbed every spare pixel and pushed the switch hundreds of
            pixels from its row. */}
        <table className="w-auto text-[13px]">
          <thead>
            <tr className="text-left text-[11.5px] text-text-3">
              <th scope="col" className="py-1.5 pr-10">Notification</th>
              <th scope="col" className="whitespace-nowrap px-3 py-1.5">In app</th>
              {chans.map((c) => (
                <th key={c.id} scope="col"
                    className="whitespace-nowrap px-3 py-1.5">{c.name}</th>
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
                  <td className="whitespace-nowrap py-1.5 pr-10 text-text-2">{r.label}</td>
                  <td className="px-3 py-1.5">
                    <Switch aria-label={r.label} checked={r.enabled}
                            disabled={setTypes.isPending}
                            onCheckedChange={() => setTypes.mutate({ [r.key]: !r.enabled })} />
                  </td>
                  {chans.map((c) => (
                    <td key={c.id} className="px-3 py-1.5">
                      <input type="checkbox"
                             // No accent utility needed: tokens.css sets
                             // accent-color on :root, so native controls
                             // inherit the amber.
                             className="size-[15px] disabled:opacity-40"
                             aria-label={`Send ${r.label} to ${c.name}`}
                             // A row that is off reaches nobody, so ticking its
                             // cells would claim a delivery that cannot happen.
                             checked={r.enabled && ticked(c, r.key)}
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

      {/* Notifications are PublicUrlField's only consumer, so it lives here. */}
      <PublicUrlField />
    </div>
  )
}
