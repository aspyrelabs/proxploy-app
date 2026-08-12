import { extractIconNames } from './icon-names.mjs'
import { buildIconFontHref } from './icon-font-link.mjs'

/**
 * Vite plugin: injects the Google Fonts <link> that serves this app's
 * Material Symbols (Outlined) icons into index.html, scoped via
 * `icon_names` to exactly the names scripts/icon-names.mjs finds referenced
 * under `srcDir`. `transformIndexHtml` is a Vite extension point, not a
 * separate script -- it runs automatically both on every dev-server request
 * for index.html and once during `vite build`, so there is nothing extra to
 * wire into package.json's `build` script the way the old
 * build-icon-font.mjs step needed.
 *
 * Re-extracts on every call rather than once at plugin-creation time, so a
 * dev-server reload after adding a new `<Icon name="...">` picks it up
 * without restarting Vite; the extraction itself is a handful of file reads
 * under src/, cheap enough to redo per request.
 *
 * @param {string} srcDir
 */
export function materialSymbolsLink(srcDir) {
  return {
    name: 'material-symbols-link',
    transformIndexHtml() {
      const names = extractIconNames(srcDir)
      return [{
        tag: 'link',
        attrs: { rel: 'stylesheet', href: buildIconFontHref(names) },
        injectTo: 'head',
      }]
    },
  }
}
