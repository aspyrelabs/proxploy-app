/** Type declaration for icon-names.mjs, co-located so TS can typecheck the
 *  test that imports it (src/tests/icon-names-extraction.test.ts,
 *  src/tests/icon-subset.test.ts) without needing scripts/ inside the app's
 *  own tsconfig "include". */
export function extractIconNames(srcDir: string): Set<string>
