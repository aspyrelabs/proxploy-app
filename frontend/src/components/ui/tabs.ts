/**
 * The underline tab strip, as class strings rather than components.
 *
 * There is no Tabs component here to wrap: routes/firewall.tsx and
 * routes/storage.tsx drive Radix's `Tabs.Root` directly and
 * routes/hosts.tsx uses TanStack `Link`s, so the only thing the three ever
 * shared was the look, and they shared it by having three copies of it.
 * Two were byte-identical; the third differed only in which selector it
 * hangs the active state on.
 *
 * `tabTrigger` therefore carries BOTH selectors. Radix stamps
 * `data-state="active"` on its own trigger; TanStack stamps a plain
 * `.active` class on a Link it considers current. Each selector is inert
 * wherever the other library is in charge, so one string serves both and
 * neither route needs to know which mechanism the other uses.
 *
 * This is a .ts, not a .tsx, for the same reason ui/overlay.ts is: it
 * exports no component, so there is no JSX in it.
 */

/** One tab. Muted until it is the current one, then full text with an amber
 *  rule under it. */
export const tabTrigger =
  'cursor-pointer px-3 py-2 text-[13px] text-text-2 transition hover:text-text ' +
  'data-[state=active]:border-b-2 data-[state=active]:border-amber data-[state=active]:text-text ' +
  '[&.active]:border-b-2 [&.active]:border-amber [&.active]:text-text'

/** The strip the tabs sit in. The hairline is what the active tab's rule
 *  reads against, so it belongs to the list rather than to any one tab. */
export const tabList = 'mb-4 mt-5 flex gap-1 border-b border-line-soft'
