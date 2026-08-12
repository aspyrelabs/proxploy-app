/** lib/notify.tsx is the one place every action notification in the app goes
 *  through (notify.success/error/info/warning, plus notify.custom for
 *  LiveProvider's already-known severities). It used to render straight into
 *  sonner's bottom-right toast stack; now it pushes into
 *  lib/notificationStore.ts, the memory NotificationSurface (the brief
 *  under-the-bell banner) and BellPopover (the tray) both read. This file
 *  covers the push itself; NotificationSurface's own test covers what
 *  showing one on screen looks like.
 */
import { describe, expect, it, beforeEach } from 'vitest'
import { notify } from '../lib/notify'
import { getNotifications, resetNotificationStore } from '../lib/notificationStore'

beforeEach(() => resetNotificationStore())

describe('notify', () => {
  it.each([
    ['success', 'success'],
    ['error', 'destructive'],
    ['info', 'info'],
    ['warning', 'warning'],
  ] as const)('notify.%s pushes a %s-severity notification', (method, severity) => {
    notify[method](`${method} title`)
    const [item] = getNotifications()
    expect(item).toMatchObject({ severity, title: `${method} title` })
  })

  // The description is never clamped or rewritten: on a failure it is the
  // reason, and a reason you cannot read in full is not a notification.
  it('a long message passed as the description is pushed in full', () => {
    const long = 'Rolling back discards every change made since the snapshot was taken, '
      + 'including any disks attached after it, and there is no way to undo a rollback '
      + 'once it starts.'
    notify.error('Could not roll back', { description: long })
    expect(getNotifications()[0].description).toBe(long)
  })

  it('each call is its own notification: two calls push two entries', () => {
    notify.error('first')
    notify.success('second')
    expect(getNotifications()).toHaveLength(2)
  })

  // LiveProvider's SSE handlers already know the card severity up front, so
  // they call straight through notify.custom rather than mapping it back to
  // one of the four names above.
  it('notify.custom pushes whatever severity it is given', () => {
    notify.custom('warning', 'staged, nothing changes until you Apply')
    expect(getNotifications()[0]).toMatchObject({ severity: 'warning' })
  })
})
