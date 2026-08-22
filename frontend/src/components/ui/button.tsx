import { forwardRef } from 'react'
import type { ButtonHTMLAttributes } from 'react'

/* ---------------------------------------------------------------------------
   Text buttons, which are class strings rather than variants.

   Twelve controls in the app are a clickable word with no box: a VM name that
   opens its row, a "Dismiss", a "Read more". Routing those through <Button>
   was tried and abandoned. The component is built around `inline-flex
   justify-center rounded-ctl` plus a size that pads, and these carry their own
   layout instead: `basis-full sm:basis-auto` in GuestList, `block max-w-full
   truncate` in IconGrid, `text-left` everywhere. Converting them meant adding
   a padding-free size and then fighting `justify-center` at every call site,
   which adds classes to delete classes.

   So they stay plain <button> elements and share the decision that was
   actually duplicated: the tint. This is the pattern LoginForm's `inputCls`
   already set, and these live here because this file is where "what a
   clickable thing looks like" is answered.

   `transition` is included: three of the ten sites were missing it and
   changed colour instantly while their neighbours eased.
   --------------------------------------------------------------------------- */

/** A row's own name, clickable, opening the thing it names. Resting text
 *  colour so it reads as content first and a control second. */
export const linkCls = 'text-text transition hover:text-amber'

/** A secondary action next to something louder: Dismiss, Advanced, Back.
 *  Muted until pointed at. Doubles as the `icon` variant below, which is the
 *  same decision applied to a glyph instead of a word. */
export const quietCls = 'text-text-3 transition hover:text-text'

/** A link onward, where amber at rest is the whole affordance because there
 *  is no surrounding chrome to say it is clickable. */
export const amberLinkCls = 'text-amber transition hover:underline'

/**
 * One option in a segmented control: a category chip, a host filter, a time
 * range, a section in a side nav.
 *
 * Six of these existed with three different selected fills (`bg-elev`,
 * `bg-panel-2`, `bg-amber-dim`), so nothing in the app taught you what
 * "selected" looks like. Amber wins because the other two were a bug, not
 * just a difference: FirewallObjects drew its selected row `bg-panel-2` and
 * its hovered row `bg-panel-2`, so pointing at an unselected group made it
 * look selected and there was no way to tell which one you had picked.
 *
 * Selected is therefore a hue change, and hover stays a surface change. Those
 * are two different signals now and cannot collide again.
 *
 * A function rather than two exported strings because every call site would
 * otherwise write the same ternary around them.
 */
export const segment = (on: boolean) =>
  on ? 'bg-amber-dim text-amber'
     : 'text-text-2 transition hover:bg-panel-2 hover:text-text'

const variants = {
  primary: 'bg-[linear-gradient(150deg,#F5B544,#E79126)] text-[#20160a] font-semibold shadow-[0_6px_18px_rgba(245,181,68,.25)] hover:brightness-105',
  ghost: 'bg-panel-2 text-text border border-line hover:bg-elev',
  danger: 'bg-red-dim text-red border border-red/30 hover:bg-red/20',
  // Start is the one action that MAKES something run, so it is the one
  // green control in the app. Built like `danger` above so the pair reads
  // as opposites of the same shape rather than two unrelated styles.
  success: 'bg-green-dim text-green border border-green/30 hover:bg-green/20',
  go: 'bg-amber-dim text-amber border border-amber/30 hover:bg-amber/20',
  // The table-row actions: edit, delete, reorder. These were ten hand-written
  // `<button>` elements before, all carrying the same two class strings,
  // because `ghost` is the wrong answer for them. A firewall rule row holds
  // four of these, so a ghost's panel fill and border would draw four boxes
  // per row and the box would out-weigh the rule the row is about.
  //
  // So: no background and no border, tint only. The affordance is the hover,
  // which is also why these two exist as a pair rather than one variant plus
  // a `hover:text-red` at every destructive call site. Delete is the majority
  // of them, and it is the one that must not be a copied class string.
  icon: quietCls,
  'icon-danger': 'text-text-3 transition hover:text-red',
} as const

// Sizes were folded into the base class list until an icon-only control needed
// a square. 'md' reproduces exactly what the base used to hardcode, so every
// existing call site renders byte-identical markup.
const sizes = {
  md: 'px-3.5 py-2 text-[13px]',
  // The small size, used only by the App Store card's Install button, where a
  // full-size control dominates a 284px fixed-height card. Whole pixels
  // rather than fractions, because a fractional font size renders blurry.
  //
  // Against md, this is:
  //   px  14px -> 9px  (-35.7%)
  //   py   8px -> 6px  (-25.0%)
  //   text 13px -> 9px (-30.8%)
  //
  // Rendered height is roughly 25px, against md's roughly 35px. That is still
  // well under the ~44px usually recommended for a touch target, so this
  // stays a deliberately small control on a touch screen; see the note at the
  // call site in components/StoreCard.tsx.
  xs: 'px-[9px] py-1.5 text-[9px]',
  // xs plus 20%, rounded to whole pixels for the same blurry-text reason:
  //   px  9px -> 11px   py 6px -> 7px   text 9px -> 11px
  // Its own entry rather than a bump to xs, because xs is load bearing for
  // the App Store card, whose 240px height the geometry harness pins.
  sm: 'px-[11px] py-[7px] text-[11px]',
  'icon-xs': 'h-6 w-6 p-0',
} as const

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: keyof typeof variants
  size?: keyof typeof sizes
}

// forwardRef so Radix's `asChild` triggers (Tooltip, Popover, DropdownMenu)
// can attach to a Button. Without it the ref lands nowhere and the trigger
// cannot position or wire aria against the element it is describing.
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = 'primary', size = 'md', className = '', ...props }, ref) {
  return (
    <button
      ref={ref}
      className={`inline-flex items-center justify-center gap-2 rounded-ctl cursor-pointer transition disabled:opacity-50 disabled:cursor-not-allowed ${sizes[size]} ${variants[variant]} ${className}`}
      {...props}
    />
  )
})
