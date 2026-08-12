/** Type declaration for icon-font-link.mjs, co-located so TS can typecheck
 *  vite.config.ts and the tests that import it without needing scripts/
 *  inside the app's own tsconfig "include". */
export function buildIconFontHref(names: Iterable<string>): string
