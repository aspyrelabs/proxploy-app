import { useMemo, useSyncExternalStore } from 'react'

/**
 * A CSS media query as React state.
 *
 * The Hosts page needs the breakpoint in JS, not just in a class: below lg the
 * two inventories stack, and a resizable split cannot express that. The
 * library lays panels out along one axis and divides that axis between them,
 * so a stacked group would divide HEIGHT and clip whichever inventory lost the
 * draw. Rendering the plain stack instead is the only version that shows every
 * app on a phone.
 *
 * Memoised on the query string: the MediaQueryList and the two callbacks have
 * to keep their identity across renders, or useSyncExternalStore tears the
 * listener down and puts it back on every one.
 */
export function useMediaQuery(query: string): boolean {
  const store = useMemo(() => {
    const mql = window.matchMedia(query)
    return {
      subscribe: (onChange: () => void) => {
        mql.addEventListener('change', onChange)
        return () => mql.removeEventListener('change', onChange)
      },
      getSnapshot: () => mql.matches,
    }
  }, [query])
  return useSyncExternalStore(store.subscribe, store.getSnapshot, () => false)
}
