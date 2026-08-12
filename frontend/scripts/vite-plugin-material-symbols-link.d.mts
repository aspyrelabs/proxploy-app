/** Type declaration for vite-plugin-material-symbols-link.mjs, co-located
 *  so TS can typecheck vite.config.ts and the test that imports it without
 *  needing scripts/ inside the app's own tsconfig "include". */
export function materialSymbolsLink(srcDir: string): {
  name: string
  transformIndexHtml(): Array<{
    tag: string
    attrs: { rel: string; href: string }
    injectTo: string
  }>
}
