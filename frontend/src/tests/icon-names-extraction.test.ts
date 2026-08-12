import { mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, describe, expect, it } from 'vitest'
import { extractIconNames } from '../../scripts/icon-names.mjs'

/**
 * scripts/icon-names.mjs is what decides which names the Google Fonts CDN
 * link's `icon_names` parameter requests (see
 * vite-plugin-material-symbols-link.mjs) -- get its extraction wrong and an
 * icon renders fine in this test suite (jsdom loads no fonts at all) but
 * shows up as the literal word in a real browser, because the CDN never
 * got asked for its glyph. These are fixture-based unit tests of the
 * extraction rule itself, in isolation from the real src/ tree;
 * src/tests/icon-names-coverage.test.tsx is the end-to-end guard that runs
 * it against real source and real renders.
 */
describe('extractIconNames', () => {
  let dir: string

  afterEach(() => {
    if (dir) rmSync(dir, { recursive: true, force: true })
  })

  const write = (relPath: string, content: string) => {
    writeFileSync(join(dir, relPath), content)
  }

  it('finds a literal name= prop on an <Icon> element', () => {
    dir = mkdtempSync(join(tmpdir(), 'icon-extract-'))
    write('A.tsx', `<Icon name="settings" size={18} />`)
    expect(extractIconNames(dir)).toEqual(new Set(['settings']))
  })

  it('finds a literal name= prop written with single quotes', () => {
    dir = mkdtempSync(join(tmpdir(), 'icon-extract-'))
    write('A.tsx', `<Icon name='close' />`)
    expect(extractIconNames(dir)).toEqual(new Set(['close']))
  })

  it('finds a name= prop that comes after other props on the same element', () => {
    dir = mkdtempSync(join(tmpdir(), 'icon-extract-'))
    write('A.tsx', `<Icon size={20} className="animate-spin" name="refresh" />`)
    expect(extractIconNames(dir)).toEqual(new Set(['refresh']))
  })

  it('finds an icon: field in a data table, e.g. NAV', () => {
    dir = mkdtempSync(join(tmpdir(), 'icon-extract-'))
    write('A.tsx', `export const NAV = [{ label: 'Hosts', icon: 'dns' }]`)
    expect(extractIconNames(dir)).toEqual(new Set(['dns']))
  })

  it('collects names across multiple files', () => {
    dir = mkdtempSync(join(tmpdir(), 'icon-extract-'))
    write('A.tsx', `<Icon name="search" />`)
    write('B.tsx', `<Icon name="close" />`)
    expect(extractIconNames(dir)).toEqual(new Set(['search', 'close']))
  })

  it('does not duplicate a name used more than once', () => {
    dir = mkdtempSync(join(tmpdir(), 'icon-extract-'))
    write('A.tsx', `<Icon name="close" />\n<Icon name="close" />`)
    expect(extractIconNames(dir)).toEqual(new Set(['close']))
  })

  it('ignores an unrelated name= prop that is not on an Icon element', () => {
    dir = mkdtempSync(join(tmpdir(), 'icon-extract-'))
    write('A.tsx', `<input name="email" />`)
    expect(extractIconNames(dir)).toEqual(new Set())
  })

  it('finds both branches of a ternary passed as name={...}', () => {
    // The real shape ThemeToggle and SidebarNav's collapse chevron use: the
    // rendered name depends on component state, so both possible literals
    // must be kept, not just whichever one a regex happens to see first.
    dir = mkdtempSync(join(tmpdir(), 'icon-extract-'))
    write('A.tsx', `<Icon name={theme === 'dark' ? 'light_mode' : 'dark_mode'} />`)
    expect(extractIconNames(dir)).toEqual(new Set(['light_mode', 'dark_mode']))
  })
})
