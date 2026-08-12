import { mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, describe, expect, it } from 'vitest'
import { materialSymbolsLink } from '../../scripts/vite-plugin-material-symbols-link.mjs'

/**
 * The plugin vite.config.ts installs to inject the Material Symbols CDN
 * <link> into index.html, both in dev (vite's transformIndexHtml hook runs
 * on every served index.html) and in a production build (it runs once,
 * writing straight into dist/index.html). Testing the plugin object
 * directly, rather than only asserting on this file's own unit-tested
 * building blocks (icon-names.mjs, icon-font-link.mjs), because wiring them
 * together into the actual Vite extension point is the one part neither of
 * those unit tests cover.
 */
describe('materialSymbolsLink', () => {
  let dir: string

  afterEach(() => {
    if (dir) rmSync(dir, { recursive: true, force: true })
  })

  it('injects a stylesheet link built from every icon name found in srcDir', () => {
    dir = mkdtempSync(join(tmpdir(), 'icon-link-plugin-'))
    writeFileSync(join(dir, 'A.tsx'), `<Icon name="settings" />`)
    const plugin = materialSymbolsLink(dir)
    const tags = plugin.transformIndexHtml()
    expect(tags).toEqual([{
      tag: 'link',
      attrs: {
        rel: 'stylesheet',
        href: expect.stringContaining('icon_names=settings') as unknown as string,
      },
      injectTo: 'head',
    }])
  })

  it('re-scans srcDir on every call, so a dev-server reload picks up a newly added icon', () => {
    dir = mkdtempSync(join(tmpdir(), 'icon-link-plugin-'))
    writeFileSync(join(dir, 'A.tsx'), `<Icon name="settings" />`)
    const plugin = materialSymbolsLink(dir)
    expect(plugin.transformIndexHtml()[0].attrs.href).toContain('icon_names=settings')

    writeFileSync(join(dir, 'A.tsx'), `<Icon name="settings" /><Icon name="close" />`)
    const href = plugin.transformIndexHtml()[0].attrs.href
    expect(href).toContain('icon_names=close,settings')
  })
})
