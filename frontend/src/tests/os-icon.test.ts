import { describe, expect, it } from 'vitest'
import { osIconUrl, osLabel } from '../lib/os-icon'

describe('osIconUrl', () => {
  it('maps every Linux ostype PVE defines', () => {
    for (const t of ['l24', 'l26']) expect(osIconUrl(t)).toBe('/linux.svg')
  })

  it('maps every Windows ostype PVE defines', () => {
    for (const t of ['wxp', 'w2k', 'w2k3', 'w2k8', 'wvista',
                     'win7', 'win8', 'win10', 'win11']) {
      expect(osIconUrl(t)).toBe('/windows.svg')
    }
  })

  it('returns null for an OS in neither family, rather than guessing', () => {
    // `solaris` is the reason this matches on the whole value and not on the
    // leading letter: a w-prefix rule would file it under Windows.
    expect(osIconUrl('solaris')).toBeNull()
    expect(osIconUrl('other')).toBeNull()
  })

  it('returns null when PVE has not told us the ostype yet', () => {
    // The common case on a fleet the poller has only just met, and the reason
    // the tile has to degrade to initials rather than to a broken image.
    expect(osIconUrl(null)).toBeNull()
    expect(osIconUrl(undefined)).toBeNull()
    expect(osIconUrl('')).toBeNull()
  })

  it('is not fooled by case or stray whitespace', () => {
    expect(osIconUrl(' L26 ')).toBe('/linux.svg')
    expect(osIconUrl('WIN11')).toBe('/windows.svg')
  })

  it('names the family for anywhere that has to say it out loud', () => {
    expect(osLabel('l26')).toBe('Linux')
    expect(osLabel('win11')).toBe('Windows')
    expect(osLabel('solaris')).toBeNull()
  })
})
