import { describe, expect, it } from 'vitest'
import { ACTION_LABEL, actionLabel } from '../components/activityDisplay'

describe('actionLabel', () => {
  it('names a mapped identifier in words', () => {
    expect(actionLabel('app.uninstall')).toBe('App Uninstalled')
    expect(actionLabel('apps.adopt')).toBe('Apps Adopted')
  })

  // The word "reaped" means nothing outside the codebase. "App Removed" also
  // has to stay DISTINCT from "App Uninstalled": an uninstall is Proxploy
  // destroying the container, a removal is Proxploy dropping its own row for a
  // container someone else already destroyed. Collapsing them would make the
  // audit log claim a destroy that never happened, so this asserts they differ
  // rather than just asserting each string.
  it('separates removing our record from destroying the container', () => {
    expect(actionLabel('app.reaped')).toBe('App Removed')
    expect(actionLabel('app.forget')).toBe('App Forgotten')
    expect(actionLabel('app.uninstall')).toBe('App Uninstalled')
    expect(actionLabel('app.reaped')).not.toBe(actionLabel('app.uninstall'))
  })

  // Backend actions get added without this map being updated; a new one must
  // still read as words, never as an empty title.
  it('derives a readable name for an identifier it has never seen', () => {
    expect(actionLabel('widget.self_destruct')).toBe('Widget Self Destruct')
    expect(actionLabel('vm.teleport')).toBe('VM Teleport')
    expect(actionLabel('')).toBe('Unknown')
    expect(actionLabel(null)).toBe('Unknown')
  })

  it('never renders a mapped label as blank', () => {
    for (const [raw, label] of Object.entries(ACTION_LABEL)) {
      expect(label.trim(), raw).not.toBe('')
    }
  })
})
