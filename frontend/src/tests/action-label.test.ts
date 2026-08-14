import { describe, expect, it } from 'vitest'
import { ACTION_LABEL, actionLabel } from '../components/activityDisplay'

describe('actionLabel', () => {
  it('names a mapped identifier in words', () => {
    expect(actionLabel('app.uninstall')).toBe('App Uninstalled')
    expect(actionLabel('apps.adopt')).toBe('Apps Adopted')
  })

  // The word "reaped" means nothing outside the codebase; the label has to
  // say what actually happened to the app.
  it('explains the self-removals rather than title-casing their jargon', () => {
    expect(actionLabel('app.reaped')).toBe('App Removed (container gone)')
    expect(actionLabel('app.forget')).toBe('App Forgotten (container kept)')
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
