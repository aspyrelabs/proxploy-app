/**
 * The underline tab strip as class strings. `tabTrigger` carries BOTH active
 * selectors because routes/firewall.tsx and routes/storage.tsx drive Radix's
 * `Tabs.Root` (stamps `data-state="active"`) while routes/hosts.tsx uses
 * TanStack `Link`s (stamps `.active`). Each selector is inert wherever the
 * other library is in charge, so one string serves both. A .ts, not .tsx,
 * because it exports no component (no JSX).
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
