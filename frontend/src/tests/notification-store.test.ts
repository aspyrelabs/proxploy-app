/** lib/notificationStore.ts is the client-side memory both notification
 *  sources feed: notify.*() (action notifications after a mutation) and
 *  LiveProvider (SSE job/alert events). BellPopover reads it merged with
 *  GET /jobs; see notification-merge.test.ts for that half.
 *
 *  This covers the store in isolation: pushing, removing, clearing, and the
 *  one thing a duplicate SSE delivery must never do -- create a second entry
 *  for the same job (applyJob's own comment notes SSE has no replay/dedup,
 *  so a duplicate delivery is a real possibility, not a hypothetical one).
 */
import { beforeEach, describe, expect, it } from 'vitest'
import {
  clearNotifications, getLastSeenAt, getNotifications, isTrayOpen, pushAction,
  pushAlertEvent, pushJobEvent, removeNotification, resetNotificationStore,
  setTrayOpen, subscribeNotifications,
} from '../lib/notificationStore'

beforeEach(() => resetNotificationStore())

describe('notificationStore', () => {
  it('pushAction adds an item with the given severity, title and description', () => {
    pushAction('success', 'Saved.', 'The change took effect immediately.')
    const items = getNotifications()
    expect(items).toHaveLength(1)
    expect(items[0]).toMatchObject({
      severity: 'success', title: 'Saved.', description: 'The change took effect immediately.',
    })
  })

  it('newest action lands first', () => {
    pushAction('info', 'first')
    pushAction('info', 'second')
    expect(getNotifications().map((i) => i.title)).toEqual(['second', 'first'])
  })

  // The core requirement: a duplicate SSE delivery of the same job's terminal
  // delta must update the existing entry, not add a second one.
  it('pushJobEvent for the same job id updates the existing entry instead of adding a second one', () => {
    pushJobEvent(42, 'info', 'app.start running')
    pushJobEvent(42, 'success', 'app.start succeeded')
    const items = getNotifications()
    expect(items).toHaveLength(1)
    expect(items[0]).toMatchObject({ severity: 'success', title: 'app.start succeeded', jobId: 42 })
  })

  it('pushJobEvent for different job ids keeps both entries', () => {
    pushJobEvent(1, 'success', 'a')
    pushJobEvent(2, 'success', 'b')
    expect(getNotifications()).toHaveLength(2)
  })

  it('pushAlertEvent never dedupes: a firing alert and its later resolution are two notifications', () => {
    pushAlertEvent(7, 'destructive', 'host-02 CPU high')
    pushAlertEvent(7, 'success', 'Resolved: host-02 CPU')
    expect(getNotifications()).toHaveLength(2)
  })

  it('removeNotification removes exactly the item asked for', () => {
    pushAction('info', 'one')
    pushAction('info', 'two')
    const [newest] = getNotifications()
    removeNotification(newest.id)
    const remaining = getNotifications()
    expect(remaining).toHaveLength(1)
    expect(remaining[0].title).toBe('one')
  })

  it('clearNotifications empties the store', () => {
    pushAction('info', 'one')
    pushAction('warning', 'two')
    clearNotifications()
    expect(getNotifications()).toEqual([])
  })

  it('notifies subscribers on push, remove and clear', () => {
    const calls: number[] = []
    const unsubscribe = subscribeNotifications(() => calls.push(1))
    pushAction('info', 'x')
    const [item] = getNotifications()
    removeNotification(item.id)
    clearNotifications()
    unsubscribe()
    pushAction('info', 'after unsubscribe')
    expect(calls).toHaveLength(3)
  })

  it('opening the tray marks the current moment as seen', () => {
    expect(isTrayOpen()).toBe(false)
    const before = getLastSeenAt()
    setTrayOpen(true)
    expect(isTrayOpen()).toBe(true)
    expect(getLastSeenAt()).toBeGreaterThanOrEqual(before)
  })

  it('closing the tray leaves lastSeenAt where opening it left it', () => {
    setTrayOpen(true)
    const seenAt = getLastSeenAt()
    setTrayOpen(false)
    expect(isTrayOpen()).toBe(false)
    expect(getLastSeenAt()).toBe(seenAt)
  })
})
