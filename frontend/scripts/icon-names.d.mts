/** Type declaration for icon-names.mjs, co-located so TS can typecheck the
 *  code that imports it (vite.config.ts via vite-plugin-material-symbols-
 *  link.mjs, src/tests/icon-names-extraction.test.ts,
 *  src/tests/icon-names-coverage.test.tsx) without needing scripts/ inside
 *  the app's own tsconfig "include". */
export function extractIconNames(srcDir: string): Set<string>
